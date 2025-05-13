import streamlit as st
import requests
import json
import uuid
from urllib.parse import urlparse, parse_qs, unquote
import pandas as pd
import time
import io
# from io import BytesIO # BytesIO sudah diimpor dari io

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
            response = requests.post(url, headers=headers, json=get_payload(page), timeout=30) # Tambahkan timeout
            response.raise_for_status() # Cek status HTTP
        except requests.exceptions.RequestException as e:
            st.error(f"Gagal mengambil URL dari halaman {page}. Error: {e}")
            # Coba tampilkan response jika ada
            try:
                st.json(response.text)
            except:
                st.text("(Tidak ada detail response)")
            break

        try:
            result_data = response.json()
            if not result_data or not isinstance(result_data, list) or not result_data[0].get('data'):
                 st.error(f"Format response tidak sesuai dari halaman {page}.")
                 st.json(result_data)
                 break

            result = result_data[0]['data']['GetShopProduct']
            if result is None: # Handle jika GetShopProduct null (misal SID salah/toko tutup)
                 st.error(f"Data 'GetShopProduct' tidak ditemukan di halaman {page}. Mungkin SID salah atau toko tidak aktif?")
                 st.json(result_data)
                 break

            urls_on_page = [p['product_url'] for p in result.get('data', []) if p and 'product_url' in p] # Lebih aman
            product_urls.extend(urls_on_page)

        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as e:
            st.error(f"Error parsing JSON dari halaman {page}: {e}")
            st.json(response.text) # Show problematic JSON text
            break

        # Cek 'links' dan 'next' dengan lebih aman
        links_data = result.get('links')
        if not links_data or not links_data.get('next'):
            break
        page += 1
        time.sleep(0.5) # Jeda bisa dikurangi jika tidak ada masalah rate limit

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

        shop_domain_val, product_key_val = path_parts[-2], path_parts[-1] # Ambil 2 bagian terakhir path
        ext_param_val = parse_qs(parsed_url.query).get('extParam', [''])[0]
    except Exception as e:
        if show_logs: st.warning(f"Error parsing URL {product_url}: {e}")
        return None

    request_url = "https://gql.tokopedia.com/graphql/PDPGetLayoutQuery"
    graphql_query = """
    query PDPGetLayoutQuery($shopDomain: String, $productKey: String, $layoutID: String, $apiVersion: Float, $userLocation: pdpUserLocation, $extParam: String, $tokonow: pdpTokoNow, $deviceID: String) {
      pdpGetLayout(shopDomain: $shopDomain, productKey: $productKey, layoutID: $layoutID, apiVersion: $apiVersion, userLocation: $userLocation, extParam: $extParam, tokonow: $tokonow, deviceID: $deviceID) {
        #requestID <-- Tidak diminta, bisa dihapus jika mau
        name
        pdpSession
        basicInfo {
          productID # Ganti id jadi productID agar lebih jelas
          shopID
          shopName
          txStats { countSold }
          stats { countReview rating }
          #ttsPID <-- ttsPID ada di level atas pdpGetLayout, bukan di basicInfo
        }
         components { # Ambil dari components jika tidak ada di pdpSession
           name
           type
           position
           # Jika ingin data lain dari components, tambahkan di sini
         }
         # Ambil ttsPID dari sini
         # Sepertinya ttsPID tidak langsung ada di response pdpGetLayout standar, perlu cek ulang query/response
         # Untuk sementara, kita set None jika tidak ditemukan
      }
    }
    """

    payload = [{
        "operationName": "PDPGetLayoutQuery",
        "variables": {
            "shopDomain": shop_domain_val, # Gunakan shop_domain dari URL
            "productKey": product_key_val,
            "layoutID": "",
            "apiVersion": 1.1, # Coba naikkan versi API
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
            # st.json(payload) # Uncomment untuk debug payload
        response = requests.post(request_url, json=payload, headers=headers_template, timeout=30)
        response.raise_for_status() # Will raise an HTTPError for bad responses (4XX or 5XX)
        response_json = response.json()

        if show_logs:
             # st.json(response_json) # Tampilkan response JSON jika log aktif
             pass # Sementara nonaktifkan agar tidak terlalu ramai

        # Cek jika ada error di response GraphQL
        if "errors" in response_json[0] and response_json[0]["errors"]:
            if show_logs: st.error(f"GraphQL Error untuk {product_url}: {response_json[0]['errors']}")
            return None # Kembalikan None jika ada error GraphQL

        # Cek apakah data pdpGetLayout ada
        pdp_layout_data = get_nested_value(response_json, [0, "data", "pdpGetLayout"])
        if not pdp_layout_data:
             if show_logs: st.warning(f"Data 'pdpGetLayout' kosong untuk {product_url}")
             # st.json(response_json) # Tampilkan response jika data kosong
             return None

        return pdp_layout_data
    except requests.exceptions.RequestException as e:
        if show_logs: st.error(f"Request gagal untuk {product_url}: {e}")
        return None
    except (IndexError, KeyError, json.JSONDecodeError) as e:
        if show_logs: st.error(f"Error parsing JSON response untuk {product_url}: {e}")
        try:
            if show_logs: st.text(response.text) # Tampilkan raw text jika JSON error
        except:
            pass
        return None
    except Exception as e: # Tangkap error lainnya
        if show_logs: st.error(f"Error tidak terduga saat memproses {product_url}: {e}")
        return None


# === Step 3: Extract Data ===
def extract_product_details(pdp_data):
    if not pdp_data:
        return None

    # --- Ekstraksi data dasar ---
    basic_info = pdp_data.get('basicInfo', {})
    stats = basic_info.get('stats', {})
    tx_stats = basic_info.get('txStats', {})

    details = {
        'ProductID': basic_info.get('productID'),
        'ShopID': basic_info.get('shopID'),
        'ShopName': basic_info.get('shopName'),
        'CountSold': tx_stats.get('countSold'),
        'CountReview': stats.get('countReview'),
        'Rating': stats.get('rating'),
        'ProductName': pdp_data.get('name'), # Ambil nama dari level atas dulu
        'PriceValue': None, # Default None
        'ttsPID': None # Default None, perlu dicari
    }

    # --- Mencari ttsPID ---
    # ttsPID terkadang ada di dalam 'components' dengan type 'main_info' atau lainnya
    # Atau bisa jadi di tempat lain tergantung struktur response terbaru
    # Kode ini mencoba mencari di components (ini hanya tebakan, perlu dicek di response asli)
    components = pdp_data.get('components', [])
    for comp in components:
        # Logika pencarian ttsPID di sini (perlu disesuaikan berdasarkan response asli)
        # Contoh: if comp.get('type') == 'some_type_containing_ttsPID': details['ttsPID'] = comp.get('data',{}).get('ttsPID')
        pass # Sementara dikosongkan karena lokasi ttsPID tidak pasti

    # --- Mencari Harga dan Nama dari pdpSession (jika ada & valid) ---
    pdp_session_str = pdp_data.get('pdpSession')
    if pdp_session_str:
        try:
            session_data = json.loads(pdp_session_str)
            # Override ProductName jika ada di session (biasanya lebih akurat)
            if 'pn' in session_data: # 'pn' sering digunakan untuk product name di session
                 details['ProductName'] = session_data['pn']
            elif 'productName' in session_data: # Coba key lain
                 details['ProductName'] = session_data['productName']

            # Ambil Harga ('pr' atau 'price')
            if 'pr' in session_data:
                details['PriceValue'] = session_data['pr']
            elif 'price' in session_data:
                details['PriceValue'] = session_data['price']

            # Coba cari ttsPID juga di session data jika belum ketemu
            if details['ttsPID'] is None:
                details['ttsPID'] = session_data.get('tid') # 'tid' kadang dipakai untuk ttsPID? perlu cek

        except json.JSONDecodeError:
            # Jika pdpSession gagal di-parse, gunakan nama dari pdp_data.get('name')
            pass # Nama sudah diambil di atas sebagai fallback
        except Exception as e:
            # Handle error lain saat proses session data
            st.warning(f"Error processing pdpSession: {e}")


    # Jika ProductName masih kosong setelah semua usaha
    if not details['ProductName']:
         details['ProductName'] = basic_info.get('name') # Fallback ke basicInfo.name

    # Final check jika ttsPID tidak ditemukan sama sekali
    # Mungkin ttsPID ada di key lain? Atau tidak tersedia di query ini?
    # Anda bisa menambahkan logika pencarian lain di sini jika tahu key yang tepat

    return details

# === Streamlit UI ===
st.set_page_config(layout="wide")
st.title("Tokopedia Produk Scraper")
sid_input = st.text_input("Masukkan SID toko Tokopedia:", "14799089") # Contoh SID
show_logs = st.checkbox("Tampilkan log detail proses (memperlambat UI dan bisa sangat panjang)")

if st.button("Execute", key="execute_button"):
    if not sid_input:
        st.error("SID Toko tidak boleh kosong!")
    elif not sid_input.isdigit():
         st.error("SID Toko harus berupa angka!")
    else:
        st.info("Memulai proses scraping...")

        # --- Headers --- (Pastikan headers up-to-date)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', # Ganti dengan User-Agent browser Anda
            'Accept': 'application/json', # Biasanya API GraphQL menerima JSON
            'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
            'Content-Type': 'application/json',
            'X-Source': 'tokopedia-lite', # Atau 'tokopedia-web'
            'X-Device': 'desktop',
            # 'X-Tkpd-Akamai': 'pdpGetLayout', # Header ini mungkin tidak selalu diperlukan atau berubah
            'Origin': 'https://www.tokopedia.com',
            'Referer': 'https://www.tokopedia.com/',
            # Tambahkan header lain jika diperlukan (misalnya cookies, x-tkpd-userid, dll., tapi hati-hati dengan info pribadi)
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"', # Sesuaikan dengan browser
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site', # Bisa juga 'same-origin' tergantung endpoint
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

            processed_count = 0 # Hitung jumlah produk yang berhasil diproses
            for i, url in enumerate(urls):
                pdp = fetch_tokopedia_product_data(url, headers, show_logs=show_logs)
                data = None # Reset data untuk setiap iterasi
                if pdp:
                    data = extract_product_details(pdp)
                    if data and data.get('ProductID'): # Pastikan ada ProductID setidaknya
                        data['ProductURL'] = url
                        all_data.append(data)
                        processed_count += 1
                    elif show_logs:
                         st.warning(f"Data tidak lengkap atau ProductID kosong untuk URL: {url}")

                # Update progress
                progress_percentage = (i + 1) / len(urls)
                elapsed_time = time.time() - start_time

                # Estimasi waktu tersisa
                eta_str = ""
                if i > 5 and elapsed_time > 1: # Buat estimasi setelah beberapa item & waktu berjalan
                    time_per_item = elapsed_time / (i + 1)
                    remaining_items = len(urls) - (i + 1)
                    eta = time_per_item * remaining_items
                    if eta > 60:
                        eta_str = f" | ETA: {eta/60:.1f} menit"
                    else:
                        eta_str = f" | ETA: {eta:.0f} detik"

                status_text.text(f"Memproses {i+1}/{len(urls)} produk... ({processed_count} berhasil) | Waktu berjalan: {elapsed_time:.1f} detik{eta_str}")
                progress_bar.progress(progress_percentage)

                # Jeda antar request detail produk
                time.sleep(0.2) # Sedikit lebih lama dari jeda URL list, bisa disesuaikan

            # --- Selesai Loop ---
            total_elapsed_time = time.time() - start_time
            status_text.text(f"Selesai! Total waktu pemrosesan: {total_elapsed_time:.1f} detik. Berhasil memproses {processed_count} dari {len(urls)} produk.")

            if all_data:
                # --- MEMBUAT DATAFRAME ---
                df_raw = pd.DataFrame(all_data)

                # --- MENGURUTKAN KOLOM SESUAI PERMINTAAN ---
                desired_column_order = [
                    'ShopID', 'ShopName', 'ProductID', 'ttsPID', 'ProductName',
                    'PriceValue', 'CountSold', 'CountReview', 'Rating', 'ProductURL'
                ]

                # Filter kolom yang ada di DataFrame untuk menghindari error jika ada kolom yang hilang
                final_columns = [col for col in desired_column_order if col in df_raw.columns]
                df = df_raw[final_columns]
                # --- SELESAI MENGURUTKAN KOLOM ---

                st.success(f"Berhasil mengekstrak data untuk {len(df)} produk.")
                st.dataframe(df)

                # --- Convert to Excel ---
                output = io.BytesIO()
                # Gunakan df (yang sudah diurutkan) untuk disimpan ke Excel
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Produk')
                excel_data = output.getvalue()

                st.download_button(
                    label="Download Data Excel",
                    data=excel_data,
                    file_name=f"tokopedia_produk_sid_{sid_input}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Tidak ada data produk valid yang berhasil diekstrak.")

# Tambahkan sedikit footer atau info tambahan jika perlu
st.markdown("---")
st.caption("Scraper Tokopedia vX.Y - Perhatikan Terms of Service Tokopedia.")
