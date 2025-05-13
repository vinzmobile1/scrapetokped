import streamlit as st
import requests
import json
import uuid
from urllib.parse import urlparse, parse_qs, unquote
import pandas as pd
import time
import io
from io import BytesIO # Redundant tapi tidak masalah

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

        try:
            response = requests.post(url, headers=headers, json=get_payload(page), timeout=30) # Tambah timeout
            response.raise_for_status() # Cek error HTTP
        except requests.exceptions.RequestException as e:
            st.error(f"Gagal mengambil URL dari halaman {page}. Error: {e}")
            # St.json(response.text) # Response mungkin tidak ada jika request gagal total
            break

        try:
            result_json = response.json()
            if not isinstance(result_json, list) or len(result_json) == 0:
                st.error(f"Format respons tidak terduga dari halaman {page}.")
                st.json(result_json)
                break

            result = result_json[0].get('data', {}).get('GetShopProduct')
            if not result:
                st.error(f"Struktur data tidak ditemukan dalam respons dari halaman {page}.")
                st.json(result_json)
                # Cek apakah ada error message dari GQL
                if 'errors' in result_json[0]:
                    st.warning(f"GraphQL Errors: {result_json[0]['errors']}")
                break

            urls_on_page = [p['product_url'] for p in result.get('data', []) if 'product_url' in p]
            product_urls.extend(urls_on_page)
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as e:
            st.error(f"Error parsing JSON dari halaman {page}: {e}")
            st.json(response.text) # Tampilkan teks mentah jika JSON error
            break


        if not get_nested_value(result, ['links', 'next']): # Gunakan helper function untuk keamanan
            break
        page += 1
        time.sleep(1) # Jeda antar halaman

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
        json_response = response.json()

        # Cek struktur respons sebelum mengakses
        if not isinstance(json_response, list) or len(json_response) == 0:
             if show_logs: st.error(f"Format respons tidak terduga untuk {product_url}")
             return None

        # Cek error GraphQL
        if 'errors' in json_response[0]:
             if show_logs: st.error(f"GraphQL error untuk {product_url}: {json_response[0]['errors']}")
             return None

        return json_response[0].get("data", {}).get("pdpGetLayout")

    except requests.exceptions.RequestException as e:
        if show_logs: st.error(f"Request gagal untuk {product_url}: {e}")
        return None
    except (IndexError, KeyError, json.JSONDecodeError) as e:
        if show_logs: st.error(f"Error parsing JSON response untuk {product_url}: {e}")
        if 'response' in locals(): # Tampilkan text jika ada response tapi JSON error
             st.text(response.text)
        return None
    except Exception as e: # Tangkap error tak terduga lainnya
        if show_logs: st.error(f"Error tak terduga saat memproses {product_url}: {e}")
        return None


# === Step 3: Extract Data ===
def extract_product_details(pdp_data):
    if not pdp_data:
        return None

    # Gunakan get_nested_value untuk keamanan
    details = {
        'ProductID': get_nested_value(pdp_data, ['basicInfo', 'id']),
        'ttsPID': get_nested_value(pdp_data, ['basicInfo', 'ttsPID']),
        'ShopID': get_nested_value(pdp_data, ['basicInfo', 'shopID']),
        'ShopName': get_nested_value(pdp_data, ['basicInfo', 'shopName']),
        'CountSold': get_nested_value(pdp_data, ['basicInfo', 'txStats', 'countSold']),
        'CountReview': get_nested_value(pdp_data, ['basicInfo', 'stats', 'countReview']),
        'Rating': get_nested_value(pdp_data, ['basicInfo', 'stats', 'rating']),
        'ProductName': get_nested_value(pdp_data, ['name']), # Default dari name
        'PriceValue': None # Default None
    }

    pdp_session_str = pdp_data.get('pdpSession')
    if pdp_session_str:
        try:
            session_data = json.loads(pdp_session_str)
            # Cek dan ambil jika ada, jika tidak gunakan default dari atas
            details['ProductName'] = get_nested_value(session_data, ['ppn'], default=details['ProductName'])
            details['PriceValue'] = get_nested_value(session_data, ['pr'])
        except json.JSONDecodeError:
            if st.checkbox("Tampilkan log detail proses (memperlambat UI)"): # Hanya log jika diminta
                 st.warning(f"Gagal decode pdpSession JSON untuk produk ID {details.get('ProductID')}. Menggunakan fallback.")
            # Fallback sudah diatur di awal
            pass

    # Pastikan tipe data numerik, ganti None atau string kosong dengan 0 jika perlu
    details['CountSold'] = int(details['CountSold'] or 0)
    details['CountReview'] = int(details['CountReview'] or 0)
    details['Rating'] = float(details['Rating'] or 0.0)
    details['PriceValue'] = float(details['PriceValue'] or 0.0) # Atau biarkan None jika 0 tidak cocok

    return details

# === Streamlit UI ===
st.set_page_config(layout="wide")
st.title("Tokopedia Produk Scraper")

# --- PERUBAHAN: Inisialisasi Session State ---
if 'scraped_data_df' not in st.session_state:
    st.session_state.scraped_data_df = None
if 'last_sid' not in st.session_state:
    st.session_state.last_sid = ""
# --- AKHIR PERUBAHAN ---

# Ambil SID dari input atau dari state jika ada data sebelumnya
sid_input_val = st.session_state.last_sid if st.session_state.scraped_data_df is not None else "14799089"
sid_input = st.text_input("Masukkan SID toko Tokopedia:", sid_input_val)
show_logs = st.checkbox("Tampilkan log detail proses (memperlambat UI)")

if st.button("Execute", key="execute_button"):
    if not sid_input:
        st.error("SID Toko tidak boleh kosong!")
    else:
        st.info("Memulai proses scraping...")
        # --- PERUBAHAN: Reset data lama sebelum scrape baru ---
        st.session_state.scraped_data_df = None
        st.session_state.last_sid = sid_input # Simpan SID yang digunakan
        # --- AKHIR PERUBAHAN ---

        headers = {
            'sec-ch-ua-platform': '"Windows"',
            'x-version': '7d93f84', # Mungkin perlu update berkala
            'sec-ch-ua': '"Not/A)Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"', # Update UA
            'x-price-center': 'true',
            'sec-ch-ua-mobile': '?0',
            # 'bd-device-id': '...', # Biasanya tidak wajib
            'x-source': 'tokopedia-lite',
            'x-tkpd-akamai': 'pdpGetLayout',
            'x-device': 'desktop',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36', # Update UA
            'accept': '*/*',
            'content-type': 'application/json',
            'x-tkpd-lite-service': 'zeus',
            'Origin': 'https://www.tokopedia.com',
            'Referer': 'https://www.tokopedia.com/',
            'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
        }

        urls = fetch_all_product_urls_from_shop(headers, sid_input)

        if not urls:
            st.warning("Tidak ada URL produk yang ditemukan atau gagal mengambil URL.")
        else:
            st.info(f"Mengambil detail untuk {len(urls)} produk...")
            all_data = []

            progress_bar = st.progress(0)
            status_text = st.empty()
            start_time = time.time()

            for i, url in enumerate(urls):
                pdp = fetch_tokopedia_product_data(url, headers, show_logs=show_logs)
                if pdp:
                    data = extract_product_details(pdp)
                    if data:
                        data['ProductURL'] = url # Tambahkan URL produk ke data
                        all_data.append(data)

                progress_percentage = (i + 1) / len(urls)
                elapsed_time = time.time() - start_time

                if i > 5 and elapsed_time > 1: # Hindari estimasi terlalu dini atau division by zero
                    time_per_item = elapsed_time / (i + 1)
                    remaining_items = len(urls) - (i + 1)
                    eta = time_per_item * remaining_items
                    eta_str = f" | ETA: {int(eta // 60)}m {int(eta % 60)}s"
                else:
                    eta_str = ""

                progress_bar.progress(progress_percentage)
                status_text.text(f"Memproses {i+1}/{len(urls)} produk... Waktu berjalan: {elapsed_time:.1f} detik{eta_str}")

                time.sleep(0.1) # Jeda kecil antar request detail produk

            total_elapsed_time = time.time() - start_time
            status_text.text(f"Selesai! Total waktu pemrosesan: {total_elapsed_time:.1f} detik.")

            if all_data:
                df = pd.DataFrame(all_data)

                # --- PERUBAHAN 1: Urutkan Kolom ---
                desired_columns = ['ShopID', 'ShopName', 'ProductID', 'ttsPID', 'ProductName', 'PriceValue', 'CountSold', 'CountReview', 'Rating', 'ProductURL']

                # Filter kolom yang ada di DataFrame untuk menghindari error jika ada yg hilang
                columns_to_order = [col for col in desired_columns if col in df.columns]
                # Tambahkan kolom lain yang mungkin ada tapi tidak di list (jika ada)
                other_columns = [col for col in df.columns if col not in columns_to_order]
                final_column_order = columns_to_order + other_columns

                df = df[final_column_order] # Terapkan urutan kolom
                # --- AKHIR PERUBAHAN 1 ---

                st.success(f"Berhasil mengambil {len(df)} produk dari {len(urls)} URL yang diproses.")

                # --- PERUBAHAN 2: Simpan ke Session State ---
                st.session_state.scraped_data_df = df
                # --- AKHIR PERUBAHAN 2 ---

            else:
                st.warning("Tidak ada data produk yang berhasil diekstrak.")
                # --- PERUBAHAN: Pastikan state kosong jika tidak ada data ---
                st.session_state.scraped_data_df = None
                # --- AKHIR PERUBAHAN ---

# --- PERUBAHAN: Tampilkan DataFrame & Tombol Download dari Session State ---
# Bagian ini akan berjalan setiap kali script di-refresh (termasuk setelah klik download)
if st.session_state.scraped_data_df is not None:
    st.dataframe(st.session_state.scraped_data_df)

    # Siapkan data Excel dari DataFrame di session state
    output = io.BytesIO()
    # Gunakan 'xlsxwriter' atau 'openpyxl' sebagai engine
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
         # Pastikan menulis data dari session state
        st.session_state.scraped_data_df.to_excel(writer, index=False, sheet_name='Produk')
    # writer.save() tidak perlu karena 'with' sudah handle

    excel_data = output.getvalue() # Dapatkan bytes setelah 'with' selesai

    st.download_button(
        label="Download Data Excel",
        data=excel_data,
        # Gunakan SID yang tersimpan dari proses scraping terakhir untuk nama file
        file_name=f"tokopedia_produk_sid_{st.session_state.last_sid}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_button" # Memberi key bisa membantu Streamlit handle state
    )
# --- AKHIR PERUBAHAN ---
