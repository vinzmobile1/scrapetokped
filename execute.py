import streamlit as st
import requests
import json
import uuid
from urllib.parse import urlparse, parse_qs, unquote
import pandas as pd
import time
import io
from io import BytesIO # BytesIO sudah diimpor dari io, jadi ini redundant, tapi tidak masalah

# === Helper Function ===
def get_nested_value(data_dict, keys, default=None):
    current = data_dict
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
            current = current[key]
        else:
            return default
    return current

# === Step 1: Fetch All Product URLs ===
def fetch_all_product_urls_from_shop(headers, sid):
    url = "https://gql.tokopedia.com/graphql/ShopProducts"

    def get_payload(page):
        return [{
            "operationName": "ShopProducts",
            "variables": {
                "source": "shop",
                "sid": sid,
                "page": page,
                "perPage": 80,
                "etalaseId": "etalase",
                "sort": 1,
                "user_districtId": "2274",
                "user_cityId": "176",
                "user_lat": "0",
                "user_long": "0"
            },
            "query": """
            query ShopProducts($sid: String!, $source: String, $page: Int, $perPage: Int, $keyword: String, $etalaseId: String, $sort: Int, $user_districtId: String, $user_cityId: String, $user_lat: String, $user_long: String) {
                GetShopProduct(shopID: $sid, source: $source, filter: {
                    page: $page, perPage: $perPage, fkeyword: $keyword,
                    fmenu: $etalaseId, sort: $sort,
                    user_districtId: $user_districtId,
                    user_cityId: $user_cityId,
                    user_lat: $user_lat, user_long: $user_long
                }) {
                    links { next }
                    data { product_url }
                }
            }
            """
        }]

    product_urls = []
    page = 1
    st.write("Memulai pengambilan URL produk...")
    page_progress_text = st.empty() # Placeholder for page progress
    start_fetch_urls_time = time.time()
    page_count = 0
    while True:
        page_count += 1
        elapsed_fetch_urls_time = time.time() - start_fetch_urls_time
        page_progress_text.text(f"Mengambil URL dari halaman {page_count}... Waktu berjalan: {elapsed_fetch_urls_time:.1f} detik")

        response = requests.post(url, headers=headers, json=get_payload(page))
        if response.status_code != 200:
            st.error(f"Gagal mengambil URL dari halaman {page}. Status: {response.status_code}")
            st.json(response.text) # Show error response
            break

        try:
            result = response.json()[0]['data']['GetShopProduct']
            urls_on_page = [p['product_url'] for p in result['data']]
            product_urls.extend(urls_on_page)
        except (IndexError, KeyError, TypeError) as e:
            st.error(f"Error parsing JSON dari halaman {page}: {e}")
            st.json(response.json()) # Show problematic JSON
            break


        if not result['links']['next']:
            break
        page += 1
        time.sleep(1) # Mengurangi dari 2 detik ke 1 detik, bisa disesuaikan

    total_fetch_urls_time = time.time() - start_fetch_urls_time
    page_progress_text.text(f"Selesai mengambil URL. Total {len(product_urls)} URL ditemukan dalam {total_fetch_urls_time:.1f} detik.")
    return product_urls

# === Step 2: Fetch Product Detail ===
def fetch_tokopedia_product_data(product_url, headers_template, show_logs=False):
    try:
        parsed_url = urlparse(product_url)
        path_parts = [part for part in parsed_url.path.split('/') if part]
        if len(path_parts) < 2:
            if show_logs: st.warning(f"URL tidak valid (path parts < 2): {product_url}")
            return None

        shop_domain_val, product_key_val = path_parts[0], path_parts[1]
        ext_param_val = parse_qs(parsed_url.query).get('extParam', [''])[0]
    except Exception as e:
        if show_logs: st.warning(f"Error parsing URL {product_url}: {e}")
        return None

    request_url = "https://gql.tokopedia.com/graphql/PDPGetLayoutQuery"
    graphql_query = """
    query PDPGetLayoutQuery($shopDomain: String, $productKey: String, $layoutID: String, $apiVersion: Float, $userLocation: pdpUserLocation, $extParam: String, $tokonow: pdpTokoNow, $deviceID: String) {
      pdpGetLayout(shopDomain: $shopDomain, productKey: $productKey, layoutID: $layoutID, apiVersion: $apiVersion, userLocation: $userLocation, extParam: $extParam, tokonow: $tokonow, deviceID: $deviceID) {
        requestID name pdpSession basicInfo {
          id: productID shopID shopName txStats { countSold } stats { countReview rating } ttsPID
        }
      }
    }
    """

    payload = [{
        "operationName": "PDPGetLayoutQuery",
        "variables": {
            "shopDomain": shop_domain_val,
            "productKey": product_key_val,
            "layoutID": "",
            "apiVersion": 1,
            "tokonow": {"shopID": "", "whID": "0", "serviceType": ""},
            "deviceID": str(uuid.uuid4()),
            "userLocation": {"cityID": "176", "addressID": "", "districtID": "2274", "postalCode": "", "latlon": ""},
            "extParam": ext_param_val
        },
        "query": graphql_query
    }]

    try:
        if show_logs:
            st.write(f"--- MENGIRIM REQUEST UNTUK: {product_url}")
        response = requests.post(request_url, json=payload, headers=headers_template, timeout=30)
        response.raise_for_status() # Will raise an HTTPError for bad responses (4XX or 5XX)
        return response.json()[0]["data"].get("pdpGetLayout")
    except requests.exceptions.RequestException as e:
        if show_logs: st.error(f"Request gagal untuk {product_url}: {e}")
        return None
    except (IndexError, KeyError, json.JSONDecodeError) as e:
        if show_logs: st.error(f"Error parsing JSON response untuk {product_url}: {e}")
        return None


# === Step 3: Extract Data ===
def extract_product_details(pdp_data):
    if not pdp_data:
        return None

    details = {
        'ProductID': get_nested_value(pdp_data, ['basicInfo', 'id']),
        'ttsPID': get_nested_value(pdp_data, ['basicInfo', 'ttsPID']),
        'ShopID': get_nested_value(pdp_data, ['basicInfo', 'shopID']),
        'ShopName': get_nested_value(pdp_data, ['basicInfo', 'shopName']),
        'CountSold': get_nested_value(pdp_data, ['basicInfo', 'txStats', 'countSold']),
        'CountReview': get_nested_value(pdp_data, ['basicInfo', 'stats', 'countReview']),
        'Rating': get_nested_value(pdp_data, ['basicInfo', 'stats', 'rating']),
    }

    pdp_session_str = pdp_data.get('pdpSession')
    if pdp_session_str:
        try:
            session_data = json.loads(pdp_session_str)
            details['ProductName'] = get_nested_value(session_data, ['ppn'])
            details['PriceValue'] = get_nested_value(session_data, ['pr'])
        except json.JSONDecodeError:
            details['ProductName'] = get_nested_value(pdp_data, ['name']) # Fallback
            details['PriceValue'] = None
    else:
        details['ProductName'] = get_nested_value(pdp_data, ['name']) # Fallback
        details['PriceValue'] = None

    return details

# === Streamlit UI ===
st.set_page_config(layout="wide")
st.title("Tokopedia Produk Scraper")
sid_input = st.text_input("Masukkan SID toko Tokopedia:", "14799089") # Contoh SID yang valid
show_logs = st.checkbox("Tampilkan log detail proses (memperlambat UI)")

if st.button("Execute", key="execute_button"):
    if not sid_input:
        st.error("SID Toko tidak boleh kosong!")
    else:
        st.info("Memulai proses scraping...")

        headers = {
            'sec-ch-ua-platform': '"Windows"',
            'x-version': '7d93f84', # Bisa jadi perlu diupdate jika ada error
            'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            'x-price-center': 'true',
            'sec-ch-ua-mobile': '?0',
            # 'bd-device-id': '1511291571156325414', # Komentari jika tidak perlu atau menyebabkan masalah
            'x-source': 'tokopedia-lite',
            'x-tkpd-akamai': 'pdpGetLayout', # Terkadang 'pdpGetLayoutV2'
            'x-device': 'desktop',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', # Update User Agent
            'accept': '*/*',
            'content-type': 'application/json',
            'x-tkpd-lite-service': 'zeus',
            'Origin': 'https://www.tokopedia.com',
            'Referer': 'https://www.tokopedia.com/', # Tambahkan Referer
            'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
        }

        urls = fetch_all_product_urls_from_shop(headers, sid_input)

        if not urls:
            st.warning("Tidak ada URL produk yang ditemukan atau gagal mengambil URL.")
        else:
            st.info(f"Mengambil detail untuk {len(urls)} produk...")
            all_data = []
            
            # --- MODIFIKASI DIMULAI DI SINI ---
            progress_bar = st.progress(0)
            status_text = st.empty() # Placeholder untuk teks status
            start_time = time.time() # Catat waktu mulai
            # --- MODIFIKASI SELESAI DI SINI ---

            for i, url in enumerate(urls):
                pdp = fetch_tokopedia_product_data(url, headers, show_logs=show_logs)
                if pdp:
                    data = extract_product_details(pdp)
                    if data:
                        data['ProductURL'] = url
                        all_data.append(data)
                
                # --- MODIFIKASI DIMULAI DI SINI ---
                progress_percentage = (i + 1) / len(urls)
                elapsed_time = time.time() - start_time # Hitung waktu yang sudah berjalan
                
                # Estimasi waktu tersisa (opsional, bisa kurang akurat di awal)
                if i > 0 : # hindari division by zero
                    time_per_item = elapsed_time / (i + 1)
                    remaining_items = len(urls) - (i + 1)
                    eta = time_per_item * remaining_items
                    eta_str = f" | ETA: {eta:.0f}s"
                else:
                    eta_str = ""

                progress_bar.progress(progress_percentage)
                status_text.text(f"Memproses {i+1}/{len(urls)} produk... Waktu berjalan: {elapsed_time:.1f} detik{eta_str}")
                # --- MODIFIKASI SELESAI DI SINI ---
                
                time.sleep(0.1) # Beri jeda sedikit agar tidak terlalu membebani server Tokopedia & UI update

            # --- MODIFIKASI DIMULAI DI SINI (setelah loop) ---
            total_elapsed_time = time.time() - start_time
            status_text.text(f"Selesai! Total waktu pemrosesan: {total_elapsed_time:.1f} detik.")
            # --- MODIFIKASI SELESAI DI SINI ---

            if all_data:
                df = pd.DataFrame(all_data)
                st.success(f"Berhasil mengambil {len(df)} produk dari {len(urls)} URL yang diproses.")
                st.dataframe(df)

                # Convert to Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Produk')
                # writer.save() tidak diperlukan lagi karena with pd.ExcelWriter sudah menghandlenya saat keluar blok
                
                st.download_button(
                    label="Download Data Excel",
                    data=output.getvalue(),
                    file_name=f"tokopedia_produk_sid_{sid_input}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Tidak ada data produk yang berhasil diekstrak.")
