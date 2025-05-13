import streamlit as st
import requests
import json
import uuid
from urllib.parse import urlparse, parse_qs, unquote
import pandas as pd
import time
import io

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

# === Fungsi Helper untuk Format Durasi Dinamis ===
def format_duration(seconds):
    if seconds < 0:
        return "segera"
    if seconds < 60:
        return f"{seconds:.1f} detik"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} menit"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} jam"

# === Step 1: Fetch All Product Info (URL, Name, Price) ===
def fetch_all_product_info_from_shop(headers, sid): # Nama fungsi diubah untuk lebih deskriptif
    url_gql = "https://gql.tokopedia.com/graphql/ShopProducts" # Ganti nama var 'url' agar tidak konflik

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
                    data {
                        product_url
                        name  # <--- DIAMBIL DI SINI
                        price { # <--- DIAMBIL DARI SINI
                            text_idr
                        }
                    }
                }
            }
            """
        }]

    product_info_list = [] # Akan menyimpan list of dictionaries
    page = 1
    st.write("Memulai pengambilan info produk awal (URL, Nama, Harga)...")
    page_progress_text = st.empty()
    start_fetch_time = time.time()
    page_count = 0
    while True:
        page_count += 1
        elapsed_fetch_time = time.time() - start_fetch_time
        page_progress_text.text(f"Mengambil info dari halaman {page_count}... Waktu berjalan: {format_duration(elapsed_fetch_time)}")

        response = requests.post(url_gql, headers=headers, json=get_payload(page))
        if response.status_code != 200:
            st.error(f"Gagal mengambil info dari halaman {page}. Status: {response.status_code}")
            st.json(response.text)
            break

        try:
            result = response.json()[0]['data']['GetShopProduct']
            products_on_page = []
            for p_data in result.get('data', []):
                product_info = {
                    'url': get_nested_value(p_data, ['product_url']),
                    'name_from_gql': get_nested_value(p_data, ['name']),
                    'price_text_from_gql': get_nested_value(p_data, ['price', 'text_idr'])
                }
                if product_info['url']: # Hanya tambahkan jika URL ada
                    products_on_page.append(product_info)
            product_info_list.extend(products_on_page)
        except (IndexError, KeyError, TypeError) as e:
            st.error(f"Error parsing JSON dari halaman {page}: {e}")
            st.json(response.json())
            break

        if not result['links']['next']:
            break
        page += 1
        time.sleep(1) # Tetap beri jeda

    total_fetch_time = time.time() - start_fetch_time
    page_progress_text.text(f"Selesai mengambil info awal. Total {len(product_info_list)} produk ditemukan dalam {format_duration(total_fetch_time)}.")
    return product_info_list

# === Step 2: Fetch Product Detail (PDP) ===
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

    request_url_gql = "https://gql.tokopedia.com/graphql/PDPGetLayoutQuery" # Ganti nama var 'url'
    graphql_query = """
    query PDPGetLayoutQuery($shopDomain: String, $productKey: String, $layoutID: String, $apiVersion: Float, $userLocation: pdpUserLocation, $extParam: String, $tokonow: pdpTokoNow, $deviceID: String) {
      pdpGetLayout(shopDomain: $shopDomain, productKey: $productKey, layoutID: $layoutID, apiVersion: $apiVersion, userLocation: $userLocation, extParam: $extParam, tokonow: $tokonow, deviceID: $deviceID) {
        requestID basicInfo { # name dan pdpSession tidak lagi digunakan untuk ProductName/PriceValue
          id: productID shopID shopName txStats { countSold } stats { countReview rating } ttsPID
        }
      }
    }
    """ # name dan pdpSession dihapus dari query PDP jika tidak ada field lain yg diambil darinya

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
            st.write(f"--- MENGIRIM REQUEST PDP UNTUK: {product_url}")
        response = requests.post(request_url_gql, json=payload, headers=headers_template, timeout=30)
        response.raise_for_status()
        return response.json()[0]["data"].get("pdpGetLayout")
    except requests.exceptions.RequestException as e:
        if show_logs: st.error(f"Request PDP gagal untuk {product_url}: {e}")
        return None
    except (IndexError, KeyError, json.JSONDecodeError) as e:
        if show_logs: st.error(f"Error parsing JSON response PDP untuk {product_url}: {e}")
        return None


# === Step 3: Extract Data ===
def extract_product_details(pdp_data, name_from_gql, price_text_from_gql):
    # pdp_data adalah hasil dari fetch_tokopedia_product_data (PDP)
    # name_from_gql dan price_text_from_gql adalah dari fetch_all_product_info_from_shop (GetShopProduct)
    if not pdp_data: # Jika PDP gagal diambil, kita mungkin masih punya nama & harga dari GQL awal
                     # Namun, detail lain seperti ProductID, ShopID akan hilang.
                     # Untuk konsistensi, jika PDP gagal, anggap seluruh data produk gagal.
        return None

    details = {
        'ProductID': get_nested_value(pdp_data, ['basicInfo', 'id']),
        'ttsPID': get_nested_value(pdp_data, ['basicInfo', 'ttsPID']),
        'ShopID': get_nested_value(pdp_data, ['basicInfo', 'shopID']),
        'ShopName': get_nested_value(pdp_data, ['basicInfo', 'shopName']),
        'CountSold': get_nested_value(pdp_data, ['basicInfo', 'txStats', 'countSold']),
        'CountReview': get_nested_value(pdp_data, ['basicInfo', 'stats', 'countReview']),
        'Rating': get_nested_value(pdp_data, ['basicInfo', 'stats', 'rating']),

        # === PERUBAHAN: ProductName dan PriceValue diambil dari argumen ===
        'ProductName': name_from_gql,
        'PriceValue': price_text_from_gql
        # === SELESAI PERUBAHAN ===
    }

    # Logika pdpSession tidak lagi diperlukan untuk ProductName dan PriceValue.
    # Jika ada field lain dari pdpSession yang ingin Anda ambil, bagian itu bisa ditambahkan kembali.
    # Berdasarkan kode sebelumnya, tidak ada field lain dari pdpSession yang diambil.

    return details

# === Streamlit UI ===
st.set_page_config(layout="wide")
st.title("Tokopedia Produk Scraper")
sid_input = st.text_input("Masukkan SID toko Tokopedia:", "14799089")
show_logs = st.checkbox("Tampilkan log detail proses (memperlambat UI)")

if st.button("Execute", key="execute_button"):
    if not sid_input:
        st.error("SID Toko tidak boleh kosong!")
    else:
        st.info("Memulai proses scraping...")

        headers = {
            'sec-ch-ua-platform': '"Windows"',
            'x-version': '7d93f84',
            'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            'x-price-center': 'true',
            'sec-ch-ua-mobile': '?0',
            'x-source': 'tokopedia-lite',
            'x-tkpd-akamai': 'pdpGetLayout', # Ini untuk PDP, untuk GetShopProduct mungkin beda, tapi seringkali header umum bisa dipakai
            'x-device': 'desktop',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'accept': '*/*',
            'content-type': 'application/json',
            'x-tkpd-lite-service': 'zeus', # Sama seperti di atas
            'Origin': 'https://www.tokopedia.com',
            'Referer': 'https://www.tokopedia.com/',
            'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
        }

        # --- PERUBAHAN: Menggunakan fungsi baru dan nama variabel baru ---
        product_initial_info_list = fetch_all_product_info_from_shop(headers, sid_input)
        # -------------------------------------------------------------

        if not product_initial_info_list:
            st.warning("Tidak ada info produk awal yang ditemukan atau gagal mengambilnya.")
        else:
            st.info(f"Mengambil detail PDP untuk {len(product_initial_info_list)} produk...")
            all_data = []
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            start_time = time.time()

            # --- PERUBAHAN: Loop melalui product_initial_info_list ---
            for i, product_info in enumerate(product_initial_info_list):
                url_item = product_info['url']
                name_from_gql = product_info['name_from_gql']
                price_from_gql = product_info['price_text_from_gql']
                # --------------------------------------------------------

                pdp_layout_data = fetch_tokopedia_product_data(url_item, headers, show_logs=show_logs)
                
                # --- PERUBAHAN: Meneruskan nama dan harga dari GQL ke extract_product_details ---
                if pdp_layout_data: # Hanya ekstrak jika PDP berhasil diambil
                    data = extract_product_details(pdp_layout_data, name_from_gql, price_from_gql)
                    if data:
                        data['ProductURL'] = url_item # Tambahkan URL produk ke data final
                        all_data.append(data)
                # Jika PDP gagal, produk ini tidak akan dimasukkan ke `all_data`
                # Alternatif: jika PDP gagal tapi ingin tetap menyimpan ProductName & PriceValue dari GQL,
                #             bisa buat struktur data minimal di sini. Namun, umumnya kita ingin data lengkap.
                # ---------------------------------------------------------------------------------
                
                progress_percentage = (i + 1) / len(product_initial_info_list)
                elapsed_time = time.time() - start_time
                
                eta_str = ""
                if i > 0 :
                    time_per_item = elapsed_time / (i + 1)
                    remaining_items = len(product_initial_info_list) - (i + 1)
                    eta = time_per_item * remaining_items
                    eta_str = f" | ETA: {format_duration(eta)}"
                else:
                    eta_str = ""

                progress_bar.progress(progress_percentage)
                status_text.text(f"Memproses {i+1}/{len(product_initial_info_list)} produk... Waktu berjalan: {format_duration(elapsed_time)}{eta_str}")
                
                time.sleep(0.1) # Jeda antar request PDP

            total_elapsed_time = time.time() - start_time
            status_text.text(f"Selesai! Total waktu pemrosesan: {format_duration(total_elapsed_time)}.")

            if all_data:
                df_raw = pd.DataFrame(all_data)

                desired_column_order = [
                    'ShopID', 'ShopName', 'ProductID', 'ttsPID', 'ProductName',
                    'PriceValue', 'CountSold', 'CountReview', 'Rating', 'ProductURL'
                ]
                current_columns = [col for col in desired_column_order if col in df_raw.columns]
                for col in df_raw.columns:
                    if col not in current_columns:
                        current_columns.append(col)
                
                df = df_raw[current_columns]

                st.success(f"Berhasil mengambil {len(df)} produk dari {len(product_initial_info_list)} URL yang diproses.")
                st.dataframe(df)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Produk')
                
                st.download_button(
                    label="Download Data Excel",
                    data=output.getvalue(),
                    file_name=f"tokopedia_produk_sid_{sid_input}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Tidak ada data produk yang berhasil diekstrak (kemungkinan karena gagal mengambil detail PDP).")
