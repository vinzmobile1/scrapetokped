import streamlit as st
import requests
import json
import uuid
from urllib.parse import urlparse, parse_qs, unquote
import pandas as pd
import time
import io
# from io import BytesIO # Sudah diimpor dari io

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
                "perPage": 80, # Maksimum per halaman
                "etalaseId": "etalase", # Ambil semua etalase
                "sort": 1, # Urutan default atau bisa disesuaikan
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
                    count # Tambahkan ini untuk melihat total produk jika API mendukung
                }
            }
            """
        }]

    product_urls = []
    page = 1
    st.write("Memulai pengambilan URL produk...")
    page_progress_text = st.empty()
    start_fetch_urls_time = time.time()
    page_count = 0
    estimated_total_products = 0 # Inisialisasi

    while True:
        page_count += 1
        elapsed_fetch_urls_time = time.time() - start_fetch_urls_time
        page_progress_text.text(f"Mengambil URL dari halaman {page_count}... Waktu berjalan: {elapsed_fetch_urls_time:.1f} detik. URL terkumpul: {len(product_urls)}")

        response = requests.post(url, headers=headers, json=get_payload(page))
        if response.status_code != 200:
            st.error(f"Gagal mengambil URL dari halaman {page}. Status: {response.status_code}")
            try:
                st.json(response.json()) # Coba tampilkan response error jika JSON
            except json.JSONDecodeError:
                st.text(response.text) # Tampilkan teks jika bukan JSON
            break

        try:
            response_data = response.json()
            if not response_data or not isinstance(response_data, list) or not response_data[0].get('data'):
                st.warning(f"Format respons tidak terduga dari halaman {page}.")
                st.json(response_data)
                break

            result = response_data[0]['data']['GetShopProduct']
            if page_count == 1 and result.get('count'): # Ambil estimasi total produk dari halaman pertama jika ada
                estimated_total_products = result['count']

            urls_on_page = [p['product_url'] for p in result.get('data', []) if p.get('product_url')]
            product_urls.extend(urls_on_page)

        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as e:
            st.error(f"Error parsing JSON atau struktur data dari halaman {page}: {e}")
            st.json(response.json())
            break

        if not result.get('links', {}).get('next'): # Lebih aman jika links atau next tidak ada
            break
        page += 1
        time.sleep(1) # Jeda antar request halaman

    total_fetch_urls_time = time.time() - start_fetch_urls_time
    page_progress_text.text(f"Selesai mengambil URL. Total {len(product_urls)} URL ditemukan dari estimasi {estimated_total_products if estimated_total_products > 0 else 'N/A'} produk dalam {total_fetch_urls_time:.1f} detik.")
    return product_urls

# === Step 2: Fetch Product Detail ===
def fetch_tokopedia_product_data(product_url, headers_template, show_logs=False):
    try:
        parsed_url = urlparse(unquote(product_url)) # unquote URL terlebih dahulu
        path_parts = [part for part in parsed_url.path.split('/') if part]
        if len(path_parts) < 2:
            if show_logs: st.warning(f"URL tidak valid (path parts < 2): {product_url}")
            return None

        shop_domain_val, product_key_val = path_parts[-2], path_parts[-1] # Ambil dua bagian terakhir dari path
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
            "layoutID": "", # Kosongkan jika tidak spesifik
            "apiVersion": 1.0, # Pastikan float
            "tokonow": {"shopID": "", "whID": "0", "serviceType": ""},
            "deviceID": str(uuid.uuid4()), # Device ID unik per request
            "userLocation": {"cityID": "176", "addressID": "", "districtID": "2274", "postalCode": "", "latlon": ""},
            "extParam": ext_param_val
        },
        "query": graphql_query
    }]

    try:
        if show_logs:
            st.write(f"--- MENGIRIM REQUEST UNTUK: {shop_domain_val}/{product_key_val}")
            # st.json(payload) # Untuk debugging payload jika perlu
        response = requests.post(request_url, json=payload, headers=headers_template, timeout=30)
        response.raise_for_status()
        json_response = response.json()
        if not json_response or not isinstance(json_response, list) or not json_response[0].get('data'):
            if show_logs: st.warning(f"Format respons PDP tidak terduga untuk {product_url}")
            return None
        return json_response[0]["data"].get("pdpGetLayout")
    except requests.exceptions.Timeout:
        if show_logs: st.error(f"Timeout saat request PDP untuk {product_url}")
        return None
    except requests.exceptions.RequestException as e:
        if show_logs: st.error(f"Request gagal untuk PDP {product_url}: {e}")
        return None
    except (IndexError, KeyError, json.JSONDecodeError) as e:
        if show_logs: st.error(f"Error parsing JSON response PDP untuk {product_url}: {e}")
        return None

# === Step 3: Extract Data ===
def extract_product_details(pdp_data):
    if not pdp_data:
        return None

    # Inisialisasi semua field yang diinginkan dengan None
    details = {
        'ShopID': None, 'ShopName': None, 'ProductID': None, 'ttsPID': None,
        'ProductName': None, 'PriceValue': None, 'CountSold': None,
        'CountReview': None, 'Rating': None
    }

    details['ProductID'] = get_nested_value(pdp_data, ['basicInfo', 'id'])
    details['ttsPID'] = get_nested_value(pdp_data, ['basicInfo', 'ttsPID'])
    details['ShopID'] = get_nested_value(pdp_data, ['basicInfo', 'shopID'])
    details['ShopName'] = get_nested_value(pdp_data, ['basicInfo', 'shopName'])
    details['CountSold'] = get_nested_value(pdp_data, ['basicInfo', 'txStats', 'countSold'])
    details['CountReview'] = get_nested_value(pdp_data, ['basicInfo', 'stats', 'countReview'])
    details['Rating'] = get_nested_value(pdp_data, ['basicInfo', 'stats', 'rating'])

    pdp_session_str = pdp_data.get('pdpSession')
    if pdp_session_str:
        try:
            session_data = json.loads(pdp_session_str)
            details['ProductName'] = get_nested_value(session_data, ['productName']) # Coba 'productName' dulu
            if not details['ProductName']: # Fallback ke 'ppn'
                 details['ProductName'] = get_nested_value(session_data, ['ppn'])
            details['PriceValue'] = get_nested_value(session_data, ['price']) # Coba 'price' dulu
            if details['PriceValue'] is None: # Fallback ke 'pr'
                 details['PriceValue'] = get_nested_value(session_data, ['pr'])
        except json.JSONDecodeError:
            # Jika pdpSession tidak bisa di-parse, gunakan nama dari pdpGetLayout
            details['ProductName'] = get_nested_value(pdp_data, ['name'])
            # PriceValue akan tetap None jika tidak ada di pdpSession
    else:
        # Jika tidak ada pdpSession, gunakan nama dari pdpGetLayout
        details['ProductName'] = get_nested_value(pdp_data, ['name'])
        # PriceValue akan tetap None

    # Pastikan tipe data numerik benar, jika tidak None
    for key in ['PriceValue', 'CountSold', 'CountReview', 'Rating']:
        if details[key] is not None:
            try:
                if key == 'Rating':
                    details[key] = float(details[key])
                else:
                    details[key] = int(details[key])
            except (ValueError, TypeError):
                # Biarkan None jika konversi gagal
                pass
        elif key in ['CountSold', 'CountReview']: # Default 0 untuk count jika None
            details[key] = 0


    return details

# === Streamlit UI ===
st.set_page_config(layout="wide")
st.title("Tokopedia Produk Scraper")

# Inisialisasi session state
if 'df_produk' not in st.session_state:
    st.session_state.df_produk = None
if 'processed_sid' not in st.session_state:
    st.session_state.processed_sid = ""

sid_input = st.text_input("Masukkan SID toko Tokopedia:", value=st.session_state.get("sid_input_val", "14799089"))
show_logs = st.checkbox("Tampilkan log detail proses (memperlambat UI)")

if st.button("Execute", key="execute_button"):
    if not sid_input:
        st.error("SID Toko tidak boleh kosong!")
    else:
        st.session_state.sid_input_val = sid_input # Simpan input SID untuk persistensi
        st.session_state.df_produk = None # Reset data sebelumnya jika execute baru
        st.session_state.processed_sid = sid_input # Tandai SID yang sedang diproses

        with st.spinner("Memulai proses scraping... Ini mungkin memakan waktu beberapa menit."):
            st.info("Mengambil data produk...")

            headers = {
                'authority': 'gql.tokopedia.com',
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9,id;q=0.8',
                'content-type': 'application/json',
                'origin': 'https://www.tokopedia.com',
                'referer': f'https://www.tokopedia.com/{sid_input}/product', # Referer yang lebih spesifik
                'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'x-device': 'desktop',
                'x-source': 'tokopedia-lite',
                'x-tkpd-akamai': 'pdpGetLayout', # atau ShopProducts tergantung endpoint
                # 'x-tkpd-lite-service': 'zeus', # Kadang diperlukan, kadang tidak
                'x-version': '2024.2.27.1', # Update berkala jika perlu
            }

            urls = fetch_all_product_urls_from_shop(headers, sid_input)

            if not urls:
                st.warning("Tidak ada URL produk yang ditemukan atau gagal mengambil URL.")
                st.session_state.df_produk = pd.DataFrame() # Set ke DataFrame kosong
            else:
                st.info(f"Mengambil detail untuk {len(urls)} produk...")
                all_data = []
                
                progress_bar = st.progress(0)
                status_text = st.empty() 
                start_time = time.time() 

                for i, url in enumerate(urls):
                    # Update header x-tkpd-akamai untuk PDP
                    pdp_headers = headers.copy()
                    pdp_headers['x-tkpd-akamai'] = 'pdpGetLayout' # Pastikan benar untuk PDP

                    pdp = fetch_tokopedia_product_data(url, pdp_headers, show_logs=show_logs)
                    if pdp:
                        data = extract_product_details(pdp)
                        if data:
                            data['ProductURL'] = url
                            all_data.append(data)
                    
                    progress_percentage = (i + 1) / len(urls)
                    elapsed_time = time.time() - start_time 
                    
                    if i > 0 : 
                        time_per_item = elapsed_time / (i + 1)
                        remaining_items = len(urls) - (i + 1)
                        eta = time_per_item * remaining_items
                        eta_str = f" | ETA: {eta:.0f}s" if eta > 0 else ""
                    else:
                        eta_str = ""

                    progress_bar.progress(progress_percentage)
                    status_text.text(f"Memproses {i+1}/{len(urls)} produk... Waktu berjalan: {elapsed_time:.1f} detik{eta_str}")
                    
                    time.sleep(0.2) # Jeda antar request detail produk (penting!)

                total_elapsed_time = time.time() - start_time
                status_text.text(f"Selesai! Total waktu pemrosesan detail: {total_elapsed_time:.1f} detik.")

                if all_data:
                    df = pd.DataFrame(all_data)
                    st.session_state.df_produk = df # Simpan ke session state
                    st.success(f"Berhasil mengambil {len(df)} produk dari {len(urls)} URL yang diproses.")
                else:
                    st.warning("Tidak ada data produk yang berhasil diekstrak.")
                    st.session_state.df_produk = pd.DataFrame() # Set ke DataFrame kosong

# Tampilkan tabel dan tombol download JIKA ada data di session_state
if st.session_state.df_produk is not None and not st.session_state.df_produk.empty:
    df_to_display = st.session_state.df_produk.copy() # Buat salinan untuk ditampilkan

    # --- MODIFIKASI URUTAN KOLOM DIMULAI DI SINI ---
    desired_columns = [
        'ShopID', 'ShopName', 'ProductID', 'ttsPID', 'ProductName',
        'PriceValue', 'CountSold', 'CountReview', 'Rating', 'ProductURL'
    ]
    # Filter kolom yang ada di DataFrame untuk menghindari KeyError jika ada kolom yang hilang
    # Meskipun extract_product_details seharusnya sudah memastikan semua ada (bisa bernilai None)
    columns_to_show = [col for col in desired_columns if col in df_to_display.columns]
    df_to_display = df_to_display[columns_to_show]
    # --- MODIFIKASI URUTAN KOLOM SELESAI DI SINI ---

    st.dataframe(df_to_display)

    # Convert to Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_to_display.to_excel(writer, index=False, sheet_name='Produk')
    # writer.save() tidak diperlukan, with statement sudah menghandle
    
    processed_sid_for_filename = st.session_state.get("processed_sid", "unknown_sid")
    st.download_button(
        label="Download Data Excel",
        data=output.getvalue(),
        file_name=f"tokopedia_produk_sid_{processed_sid_for_filename}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_excel_button" # Tambahkan key untuk download button
    )
elif st.session_state.df_produk is not None and st.session_state.df_produk.empty:
    # Jika df_produk ada tapi kosong (misal tidak ada URL ditemukan atau tidak ada data diekstrak)
    st.info("Tidak ada data produk untuk ditampilkan atau diunduh.")
