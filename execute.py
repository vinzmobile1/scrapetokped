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
    while True:
        response = requests.post(url, headers=headers, json=get_payload(page))
        if response.status_code != 200:
            break

        result = response.json()[0]['data']['GetShopProduct']
        urls = [p['product_url'] for p in result['data']]
        product_urls.extend(urls)

        if not result['links']['next']:
            break
        page += 1
        time.sleep(2)

    return product_urls

# === Step 2: Fetch Product Detail ===
def fetch_tokopedia_product_data(product_url, headers_template):
    try:
        parsed_url = urlparse(product_url)
        path_parts = [part for part in parsed_url.path.split('/') if part]
        if len(path_parts) < 2:
            return None

        shop_domain_val, product_key_val = path_parts[0], path_parts[1]
        ext_param_val = parse_qs(parsed_url.query).get('extParam', [''])[0]
    except:
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
        response = requests.post(request_url, json=payload, headers=headers_template, timeout=30)
        response.raise_for_status()
        return response.json()[0]["data"].get("pdpGetLayout")
    except:
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
        except:
            details['ProductName'] = get_nested_value(pdp_data, ['name'])
            details['PriceValue'] = None
    else:
        details['ProductName'] = get_nested_value(pdp_data, ['name'])
        details['PriceValue'] = None

    return details

# === Streamlit UI ===
st.title("Tokopedia Produk Scraper")
sid_input = st.text_input("Masukkan SID toko Tokopedia:", "10726874")
if st.button("Execute"):
    st.info("Mengambil data produk...")

    headers = {
        'sec-ch-ua-platform': '"Windows"',
        'x-version': '7d93f84',
        'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        'x-price-center': 'true',
        'sec-ch-ua-mobile': '?0',
        'bd-device-id': '1511291571156325414',
        'x-source': 'tokopedia-lite',
        'x-tkpd-akamai': 'pdpGetLayout',
        'x-device': 'desktop',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'accept': '*/*',
        'content-type': 'application/json',
        'x-tkpd-lite-service': 'zeus',
        'Origin': 'https://www.tokopedia.com',
        'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
    }

    urls = fetch_all_product_urls_from_shop(headers, sid_input)
    all_data = []

    for url in urls:
        pdp = fetch_tokopedia_product_data(url, headers)
        if pdp:
            data = extract_product_details(pdp)
            if data:
                data['ProductURL'] = url
                all_data.append(data)

    if all_data:
        df = pd.DataFrame(all_data)
        st.success(f"Berhasil mengambil {len(df)} produk.")
        st.dataframe(df)

        # Convert to Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Produk')
            writer.save()
        st.download_button("Download Excel", output.getvalue(), "tokopedia_produk.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.warning("Tidak ada data produk ditemukan.")
