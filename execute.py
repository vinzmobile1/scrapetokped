import streamlit as st
import requests
import json
import uuid
from urllib.parse import urlparse, parse_qs
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

# === Step 1: Fetch Initial Product Data from ShopProducts ===
def fetch_initial_product_data_from_shop(headers, sid):
    url_gql_shop_products = "https://gql.tokopedia.com/graphql/ShopProducts"

    def get_payload(page):
        return [{
            "operationName": "ShopProducts",
            "variables": {
                "source": "shop",
                "sid": sid,
                "page": page,
                "perPage": 80, # Ambil maksimal 80 per halaman
                "etalaseId": "etalase", # atau "" untuk semua etalase
                "sort": 1, # Urutan default
                "user_districtId": "2274", # Contoh, bisa dikosongkan
                "user_cityId": "176",     # Contoh, bisa dikosongkan
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
                        product_id  # ID Produk dari ShopProducts
                        name        # Nama Produk
                        product_url # URL Produk
                        price {     # Harga
                            text_idr
                        }
                    }
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
            response.raise_for_status() # Cek HTTP errors
        except requests.exceptions.RequestException as e:
            st.error(f"Request ke ShopProducts halaman {page} gagal: {e}")
            break # Hentikan jika request gagal

        try:
            gql_response_data = response.json()
            if not gql_response_data or not isinstance(gql_response_data, list) or not gql_response_data[0].get('data'):
                st.warning(f"Struktur respons ShopProducts tidak valid dari halaman {page}.")
                if show_logs: st.json(gql_response_data)
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
            if show_logs: st.json(response.text) # Tampilkan raw text jika parsing gagal
            break

        if not result_gql.get('links', {}).get('next'):
            break
        page += 1
        time.sleep(0.5) # Jeda antar halaman ShopProducts

    total_fetch_time = time.time() - start_fetch_time
    page_progress_text.text(f"Selesai mengambil data awal dari ShopProducts. Total {len(initial_product_data_list)} produk ditemukan dalam {format_duration(total_fetch_time)}.")
    return initial_product_data_list

# === Step 2: Fetch Additional Product Detail from PDPGetLayoutQuery ===
def fetch_pdp_details(product_url, headers_template, show_logs_local=False): # Tambahkan show_logs_local
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
    if not pdp_details_data or not pdp_details_data.get('basicInfo'):
        return None # Membutuhkan basicInfo dari PDP

    final_details = {
        'ProductName': initial_data.get('name_shop'),
        'PriceValue': initial_data.get('price_text_shop'),
        'ProductURL': initial_data.get('url_shop'),
        # 'ProductID_from_ShopProducts': initial_data.get('product_id_shop'), # Opsional jika ingin disimpan

        'ProductID': get_nested_value(pdp_details_data, ['basicInfo', 'id']),
        'ttsPID': get_nested_value(pdp_details_data, ['basicInfo', 'ttsPID']),
        'ShopID': get_nested_value(pdp_details_data, ['basicInfo', 'shopID']),
        'ShopName': get_nested_value(pdp_details_data, ['basicInfo', 'shopName']),
        'CountSold': get_nested_value(pdp_details_data, ['basicInfo', 'txStats', 'countSold']),
        'CountReview': get_nested_value(pdp_details_data, ['basicInfo', 'stats', 'countReview']),
        'Rating': get_nested_value(pdp_details_data, ['basicInfo', 'stats', 'rating']),
    }
    return final_details

# === Streamlit UI ===
st.set_page_config(layout="wide")
st.title("Tokopedia Produk Scraper v3")
sid_input = st.text_input("Masukkan SID toko Tokopedia:", "14799089") # Contoh SID
show_logs = st.checkbox("Tampilkan log detail proses (memperlambat UI)") # Variabel global untuk logging

if st.button("Execute", key="execute_button"):
    if not sid_input:
        st.error("SID Toko tidak boleh kosong!")
    else:
        st.info("Memulai proses scraping...")

        # Header umum, bisa di-override jika perlu
        common_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'accept': '*/*',
            'content-type': 'application/json',
            'Origin': 'https://www.tokopedia.com',
            'Referer': 'https://www.tokopedia.com/', # Referer umum
            'x-source': 'tokopedia-lite', # Umumnya aman
            'x-device': 'desktop',       # Umumnya aman
        }

        # Headers spesifik untuk ShopProducts (jika ada yang berbeda)
        headers_shop_products = common_headers.copy()
        # headers_shop_products['x-tkpd-akamai'] = 'shopsearch' # Contoh jika perlu

        # Tahap 1: Ambil data awal dari ShopProducts
        initial_product_list = fetch_initial_product_data_from_shop(headers_shop_products, sid_input)

        if not initial_product_list:
            st.warning("Tidak ada data awal produk yang ditemukan dari ShopProducts.")
        else:
            st.info(f"Mengambil detail tambahan (PDP) untuk {len(initial_product_list)} produk...")
            all_combined_data = []
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            start_processing_time = time.time()

            for i, initial_data_item in enumerate(initial_product_list):
                product_url_for_pdp = initial_data_item.get('url_shop')
                
                # Headers spesifik untuk PDPGetLayoutQuery
                headers_pdp_query = common_headers.copy()
                headers_pdp_query['x-tkpd-akamai'] = 'pdpGetLayout' # Ini penting untuk PDP
                
                pdp_details = fetch_pdp_details(product_url_for_pdp, headers_pdp_query, show_logs_local=show_logs)
                
                if pdp_details:
                    combined_data = combine_and_extract_product_data(initial_data_item, pdp_details)
                    if combined_data:
                        all_combined_data.append(combined_data)
                    elif show_logs:
                        st.warning(f"Gagal menggabungkan data untuk URL: {product_url_for_pdp}. Initial: {initial_data_item}, PDP: {pdp_details}")
                elif show_logs and product_url_for_pdp: # Hanya log jika URL ada tapi PDP gagal
                    st.warning(f"Gagal mengambil detail PDP untuk URL: {product_url_for_pdp}")
                
                progress_percentage = (i + 1) / len(initial_product_list)
                elapsed_time = time.time() - start_processing_time
                
                eta_str = ""
                if i > 0 and progress_percentage < 1: # Hanya hitung ETA jika sudah ada item dan belum selesai
                    time_per_item = elapsed_time / (i + 1)
                    remaining_items = len(initial_product_list) - (i + 1)
                    eta = time_per_item * remaining_items
                    eta_str = f" | ETA: {format_duration(eta)}"
                
                progress_bar.progress(progress_percentage)
                status_text.text(f"Memproses {i+1}/{len(initial_product_list)} produk... Waktu berjalan: {format_duration(elapsed_time)}{eta_str}")
                
                time.sleep(0.1) # Jeda antar request PDP (bisa disesuaikan)

            total_processing_time = time.time() - start_processing_time
            status_text.text(f"Selesai! Total waktu pemrosesan detail: {format_duration(total_processing_time)}.")

            if all_combined_data:
                df_final = pd.DataFrame(all_combined_data)

                desired_column_order = [
                    'ShopID', 'ShopName', 'ProductID', 'ttsPID', 'ProductName',
                    'PriceValue', 'CountSold', 'CountReview', 'Rating', 'ProductURL'
                ]
                final_columns_ordered = [col for col in desired_column_order if col in df_final.columns]
                for col in df_final.columns: # Tambahkan kolom yang tidak ada di desired_column_order ke akhir
                    if col not in final_columns_ordered:
                        final_columns_ordered.append(col)
                
                df_final = df_final[final_columns_ordered]

                st.success(f"Berhasil mengambil dan menggabungkan data untuk {len(df_final)} produk.")
                st.dataframe(df_final)

                output_excel = io.BytesIO()
                with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False, sheet_name='Produk')
                
                st.download_button(
                    label="Download Data Excel",
                    data=output_excel.getvalue(),
                    file_name=f"tokopedia_produk_sid_{sid_input}_final.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Tidak ada data produk final yang berhasil diekstrak dan digabungkan.")
