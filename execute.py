import streamlit as st
import requests
import json
import uuid
from urllib.parse import urlparse, parse_qs
import pandas as pd
import time
import io

# === Helper Function ===
# ... (kode helper Anda tetap sama) ...
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

# === Step 1: Fetch Initial Product Data from ShopProducts ===
def fetch_initial_product_data_from_shop(headers, sid, show_logs_local): # Tambahkan show_logs_local
    url_gql_shop_products = "https://gql.tokopedia.com/graphql/ShopProducts"

    def get_payload(page):
        return [{
            "operationName": "ShopProducts",
            "variables": {
                "source": "shop", "sid": sid, "page": page, "perPage": 80,
                "etalaseId": "etalase", "sort": 1, "user_districtId": "2274",
                "user_cityId": "176", "user_lat": "0", "user_long": "0"
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
                    data { product_id name product_url price { text_idr } }
                }
            }
            """
        }]

    initial_product_data_list = []
    page = 1
    st.write("Memulai pengambilan data awal produk dari ShopProducts...")
    page_progress_text = st.empty()
    start_fetch_time = time.time()
    page_count = 0
    while True:
        page_count += 1
        elapsed_fetch_time = time.time() - start_fetch_time
        page_progress_text.text(f"Mengambil data awal dari halaman {page_count}... | Waktu berjalan: {format_duration(elapsed_fetch_time)}")

        try:
            response = requests.post(url_gql_shop_products, headers=headers, json=get_payload(page), timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            st.error(f"Request ke ShopProducts halaman {page} gagal: {e}")
            break

        try:
            gql_response_data = response.json()
            if not gql_response_data or not isinstance(gql_response_data, list) or not gql_response_data[0].get('data'):
                st.warning(f"Struktur respons ShopProducts tidak valid dari halaman {page}.")
                if show_logs_local: st.json(gql_response_data) # Gunakan show_logs_local
                break

            result_gql = gql_response_data[0]['data']['GetShopProduct']
            products_on_page = []
            for p_data in result_gql.get('data', []):
                product_info = {
                    'product_id_shop': get_nested_value(p_data, ['product_id']),
                    'name_shop': get_nested_value(p_data, ['name']),
                    'url_shop': get_nested_value(p_data, ['product_url']),
                    'price_text_shop': get_nested_value(p_data, ['price', 'text_idr'])
                }
                if product_info['url_shop']:
                    products_on_page.append(product_info)
            initial_product_data_list.extend(products_on_page)
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as e:
            st.error(f"Error parsing JSON dari ShopProducts halaman {page}: {e}")
            if show_logs_local: st.json(response.text) # Gunakan show_logs_local
            break

        if not result_gql.get('links', {}).get('next'):
            break
        page += 1
        time.sleep(1)

    total_fetch_time = time.time() - start_fetch_time
    page_progress_text.text(f"Selesai mengambil data awal dari ShopProducts. Total {len(initial_product_data_list)} produk ditemukan dalam {format_duration(total_fetch_time)}.")
    return initial_product_data_list

# === Step 2: Fetch Additional Product Detail from PDPGetLayoutQuery ===
def fetch_pdp_details(product_url, headers_template, show_logs_local=False):
    # ... (kode fetch_pdp_details Anda tetap sama, pastikan show_logs_local digunakan dengan benar) ...
    if not product_url:
        if show_logs_local: st.warning("URL produk kosong, tidak dapat mengambil detail PDP.")
        return None
    try:
        parsed_url = urlparse(product_url)
        path_parts = [part for part in parsed_url.path.split('/') if part]
        if len(path_parts) < 2:
            if show_logs_local: st.warning(f"URL tidak valid untuk PDP (path parts < 2): {product_url}")
            return None

        shop_domain_val, product_key_val = path_parts[0], path_parts[1]
        ext_param_val = parse_qs(parsed_url.query).get('extParam', [''])[0]
    except Exception as e:
        if show_logs_local: st.warning(f"Error parsing URL untuk PDP {product_url}: {e}")
        return None

    request_url_pdp = "https://gql.tokopedia.com/graphql/PDPGetLayoutQuery"
    graphql_query_pdp = """
    query PDPGetLayoutQuery($shopDomain: String, $productKey: String, $layoutID: String, $apiVersion: Float, $userLocation: pdpUserLocation, $extParam: String, $tokonow: pdpTokoNow, $deviceID: String) {
      pdpGetLayout(shopDomain: $shopDomain, productKey: $productKey, layoutID: $layoutID, apiVersion: $apiVersion, userLocation: $userLocation, extParam: $extParam, tokonow: $tokonow, deviceID: $deviceID) {
        basicInfo {
          id: productID
          shopID
          shopName
          txStats { countSold }
          stats { countReview rating }
          ttsPID
          createdAt
        }
      }
    }
    """
    payload = [{
        "operationName": "PDPGetLayoutQuery",
        "variables": {
            "shopDomain": shop_domain_val,
            "productKey": product_key_val,
            "layoutID": "", "apiVersion": 1,
            "tokonow": {"shopID": "", "whID": "0", "serviceType": ""},
            "deviceID": str(uuid.uuid4()),
            "userLocation": {"cityID": "176", "addressID": "", "districtID": "2274", "postalCode": "", "latlon": ""},
            "extParam": ext_param_val
        },
        "query": graphql_query_pdp
    }]

    try:
        if show_logs_local: st.write(f"--- MENGIRIM REQUEST PDP UNTUK: {product_url}")
        response = requests.post(request_url_pdp, json=payload, headers=headers_template, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0 and data[0].get('data'):
            return data[0]['data'].get("pdpGetLayout")
        if show_logs_local: st.warning(f"Struktur JSON response PDP tidak sesuai untuk {product_url}: {data}")
        return None
    except requests.exceptions.RequestException as e:
        if show_logs_local: st.error(f"Request PDP gagal untuk {product_url}: {e}")
        return None
    except (IndexError, KeyError, AttributeError, json.JSONDecodeError) as e:
        if show_logs_local: st.error(f"Error parsing JSON response PDP untuk {product_url}: {e}")
        return None

# === Step 3: Combine and Extract Final Data ===
def combine_and_extract_product_data(initial_data, pdp_details_data):
    # ... (kode combine_and_extract_product_data Anda tetap sama) ...
    if not pdp_details_data or not pdp_details_data.get('basicInfo'):
        return None

    final_details = {
        'ProductName': initial_data.get('name_shop'),
        'PriceValue': initial_data.get('price_text_shop'),
        'ProductURL': initial_data.get('url_shop'),
        'ProductID': str(get_nested_value(pdp_details_data, ['basicInfo', 'id'])),
        'ttsPID': str(get_nested_value(pdp_details_data, ['basicInfo', 'ttsPID'])),
        'ShopID': str(get_nested_value(pdp_details_data, ['basicInfo', 'shopID'])),
        'ShopName': get_nested_value(pdp_details_data, ['basicInfo', 'shopName']),
        'CountSold': int(get_nested_value(pdp_details_data, ['basicInfo', 'txStats', 'countSold'],0)), # default to 0
        'CountReview': int(get_nested_value(pdp_details_data, ['basicInfo', 'stats', 'countReview'],0)), # default to 0
        'Rating': str(get_nested_value(pdp_details_data, ['basicInfo', 'stats', 'rating'],0)), # default to 0
        'createdAt': get_nested_value(pdp_details_data, ['basicInfo', 'createdAt']),
    }
    return final_details

# === Streamlit UI ===
st.set_page_config(layout="wide", page_title="Naufal - Scrape Tokopedia")
st.title("Tokopedia Produk Scraper")

# --- INISIALISASI SESSION STATE ---
if 'scraping_in_progress' not in st.session_state:
    st.session_state.scraping_in_progress = False
if 'scraping_finished' not in st.session_state:
    st.session_state.scraping_finished = False
if 'initial_product_list' not in st.session_state:
    st.session_state.initial_product_list = []
if 'all_combined_data' not in st.session_state:
    st.session_state.all_combined_data = []
if 'current_item_index' not in st.session_state:
    st.session_state.current_item_index = 0
if 'log_messages' not in st.session_state: # Untuk log yang persisten
    st.session_state.log_messages = []
if 'sid_input_value' not in st.session_state: # Simpan SID input
    st.session_state.sid_input_value = "14799089" # Contoh SID

# Gunakan nilai dari session state untuk input dan checkbox
sid_input = st.text_input(
    "Masukkan SID toko Tokopedia:",
    value=st.session_state.sid_input_value,
    key="sid_input_key" # Beri key agar Streamlit bisa track
)
# Update session state jika input berubah
st.session_state.sid_input_value = sid_input


# --- KELOLA SHOW_LOGS DENGAN SESSION STATE ---
if 'show_logs_value' not in st.session_state:
    st.session_state.show_logs_value = False

show_logs = st.checkbox(
    "Tampilkan log detail proses (memperlambat UI)",
    value=st.session_state.show_logs_value,
    key="show_logs_checkbox"
)
# Update session state jika checkbox berubah
st.session_state.show_logs_value = show_logs
# --- SELESAI KELOLA SHOW_LOGS ---


# Tombol Execute
execute_button_col, reset_button_col = st.columns(2)
with execute_button_col:
    if st.button("Execute", key="execute_button", disabled=st.session_state.scraping_in_progress):
        if not sid_input:
            st.error("SID Toko tidak boleh kosong!")
        else:
            # Reset state sebelum memulai scraping baru
            st.session_state.scraping_in_progress = True
            st.session_state.scraping_finished = False
            st.session_state.initial_product_list = []
            st.session_state.all_combined_data = []
            st.session_state.current_item_index = 0
            st.session_state.log_messages = []
            st.info("Memulai proses scraping...")
            # Panggil re-run agar proses dimulai di iterasi berikutnya
            st.experimental_rerun()

with reset_button_col:
    if st.button("Reset Proses", key="reset_button"):
        # Reset semua state yang relevan
        st.session_state.scraping_in_progress = False
        st.session_state.scraping_finished = False
        st.session_state.initial_product_list = []
        st.session_state.all_combined_data = []
        st.session_state.current_item_index = 0
        st.session_state.log_messages = []
        st.info("Proses direset. Silakan masukkan SID baru dan Execute.")
        st.experimental_rerun()

# --- LOGIKA SCRAPING UTAMA ---
if st.session_state.scraping_in_progress and not st.session_state.scraping_finished:
    common_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'accept': '*/*', 'content-type': 'application/json', 'Origin': 'https://www.tokopedia.com',
        'Referer': 'https://www.tokopedia.com/', 'x-source': 'tokopedia-lite', 'x-device': 'desktop',
    }
    headers_shop_products = common_headers.copy()
    headers_pdp_query = common_headers.copy()
    headers_pdp_query['x-tkpd-akamai'] = 'pdpGetLayout'

    # Tahap 1: Ambil data awal (jika belum ada)
    if not st.session_state.initial_product_list:
        st.session_state.initial_product_list = fetch_initial_product_data_from_shop(
            headers_shop_products,
            st.session_state.sid_input_value, # Gunakan SID dari session state
            st.session_state.show_logs_value # Gunakan show_logs dari session state
        )
        if not st.session_state.initial_product_list:
            st.warning("Tidak ada data awal produk yang ditemukan dari ShopProducts.")
            st.session_state.scraping_in_progress = False # Hentikan jika tidak ada data
            st.session_state.scraping_finished = True # Anggap selesai
            st.experimental_rerun() # Perbarui UI
        else:
            st.info(f"Mengambil detail tambahan (PDP) untuk {len(st.session_state.initial_product_list)} produk...")
            st.session_state.current_item_index = 0 # Mulai dari awal untuk PDP

    # Tahap 2 & 3: Proses PDP dan gabungkan data (jika ada data awal)
    if st.session_state.initial_product_list:
        progress_bar = st.progress(0)
        status_text = st.empty()
        start_processing_time = time.time() # Ini bisa di-refine jika ingin melanjutkan dari tengah

        # Loop melalui item yang belum diproses
        initial_list_len = len(st.session_state.initial_product_list)
        while st.session_state.current_item_index < initial_list_len:
            i = st.session_state.current_item_index
            initial_data_item = st.session_state.initial_product_list[i]
            product_url_for_pdp = initial_data_item.get('url_shop')

            pdp_details = fetch_pdp_details(
                product_url_for_pdp,
                headers_pdp_query,
                show_logs_local=st.session_state.show_logs_value # Gunakan show_logs dari session state
            )

            if pdp_details:
                combined_data = combine_and_extract_product_data(initial_data_item, pdp_details)
                if combined_data:
                    st.session_state.all_combined_data.append(combined_data)
                elif st.session_state.show_logs_value:
                    st.warning(f"Gagal menggabungkan data untuk URL: {product_url_for_pdp}. Initial: {initial_data_item}, PDP: {pdp_details}")
            elif st.session_state.show_logs_value and product_url_for_pdp:
                st.warning(f"Gagal mengambil detail PDP untuk URL: {product_url_for_pdp}")

            st.session_state.current_item_index += 1
            progress_percentage = st.session_state.current_item_index / initial_list_len
            elapsed_time = time.time() - start_processing_time # Perlu diatur ulang jika resume
            
            eta_str = ""
            if st.session_state.current_item_index > 0 and progress_percentage < 1:
                time_per_item = elapsed_time / st.session_state.current_item_index
                remaining_items = initial_list_len - st.session_state.current_item_index
                eta = time_per_item * remaining_items
                eta_str = f" | ETA: {format_duration(eta)}"
            
            progress_bar.progress(progress_percentage)
            status_text.text(f"Memproses {st.session_state.current_item_index}/{initial_list_len} produk... | Waktu berjalan: {format_duration(elapsed_time)}{eta_str}")
            time.sleep(0.1)

            # Jika Anda ingin lebih responsif terhadap perubahan show_logs selama proses PDP,
            # Anda mungkin perlu memanggil st.experimental_rerun() di sini,
            # tetapi itu akan membuat ETA dan waktu berjalan direset setiap kali.
            # Biasanya, lebih baik biarkan selesai atau tambahkan tombol 'Pause/Resume'.

        # Setelah loop selesai
        st.session_state.scraping_finished = True
        st.session_state.scraping_in_progress = False
        total_processing_time = time.time() - start_processing_time # Perlu diatur ulang jika resume
        status_text.text(f"Selesai! Total waktu pemrosesan detail: {format_duration(total_processing_time)}.")
        st.experimental_rerun() # Perbarui UI untuk menampilkan hasil

# --- TAMPILKAN HASIL JIKA SELESAI ---
if st.session_state.scraping_finished and st.session_state.all_combined_data:
    df_final = pd.DataFrame(st.session_state.all_combined_data)
    desired_column_order = [
        'ShopID', 'ShopName', 'ProductID', 'ttsPID', 'ProductName',
        'PriceValue', 'CountSold', 'CountReview', 'Rating', 'ProductURL', 'createdAt'
    ]
    # Pastikan semua kolom ada, jika tidak, tambahkan yang hilang dari df_final.columns
    final_columns_ordered = [col for col in desired_column_order if col in df_final.columns]
    for col in df_final.columns:
        if col not in final_columns_ordered:
            final_columns_ordered.append(col)
    
    df_final = df_final[final_columns_ordered]

    st.success(f"Berhasil mengambil dan menggabungkan data untuk {len(df_final)} produk.")
    column_rename_map = {
        'ShopID': "Shop ID", 'ShopName': "Shop Name", 'ProductID': "Product ID",
        'ttsPID': "SKU", 'ProductName': "Product Name", 'PriceValue': "Price",
        'CountSold': "Count Sold", 'CountReview': "Count Review", 'Rating': "Rating",
        'ProductURL': "Product URL", 'createdAt' : "createdAt"
    }
    df_display = df_final.copy()
    actual_rename_map = {k: v for k, v in column_rename_map.items() if k in df_display.columns}
    df_display.rename(columns=actual_rename_map, inplace=True)
    
    st.dataframe(df_display, hide_index=True)

    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        df_final.to_excel(writer, index=False, sheet_name='Produk')
    
    st.download_button(
        label="Download Data Excel",
        data=output_excel.getvalue(),
        file_name=f"tokopedia_produk_sid_{st.session_state.sid_input_value}_final.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
elif st.session_state.scraping_finished and not st.session_state.all_combined_data:
    st.warning("Tidak ada data produk final yang berhasil diekstrak dan digabungkan.")

# Tampilkan log jika ada
if st.session_state.show_logs_value and st.session_state.log_messages:
    st.subheader("Log Proses:")
    for msg in st.session_state.log_messages:
        st.text(msg)
