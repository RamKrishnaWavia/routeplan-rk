import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import datetime

# --- PAGE SETUP ---
st.set_page_config(page_title="BBD Performance Dashboard", layout="wide")
st.title("📊 BBD Migration - Performance Executive Dashboard")

# --- UTILITY FUNCTIONS ---
def load_file(keyword):
    """Search for files matching the keyword (case-insensitive)"""
    all_files = os.listdir('.')
    matches = [f for f in all_files if keyword.lower() in f.lower() and f.endswith(('.csv', '.xlsx'))]
    if not matches:
        return None
    target = matches[0]
    try:
        if target.endswith('.csv'):
            return pd.read_csv(target, low_memory=False)
        else:
            return pd.read_excel(target, engine='openpyxl')
    except Exception as e:
        st.error(f"Error loading {target}: {e}")
        return None

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("Settings")
    lang = st.radio("Select Language / மொழியைத் தேர்ந்தெடுக்கவும்", ["English", "Tamil"])
    show_charts = st.checkbox("Show Performance Charts", value=True)
    process_btn = st.button("🚀 Generate Dashboard")

# --- DICTIONARY FOR MAPPING ---
target_cols = {
    'delivery_date': 'Date' if lang == "English" else 'தேதி',
    'sa_name': 'Store Name' if lang == "English" else 'கிளை பெயர்',
    'total_customers': 'Unique Customers' if lang == "English" else 'தனிப்பட்ட வாடிக்கையாளர்கள்',
    'total_orders': 'Total Orders' if lang == "English" else 'மொத்த ஆர்டர்கள்',
    'orders_delivered': 'Orders Delivered' if lang == "English" else 'விநியோகிக்கப்பட்டவை',
    'sub_orders': 'Subscription Orders' if lang == "English" else 'சந்தா ஆர்டர்கள்',
    'topup_orders': 'Top-up Orders' if lang == "English" else 'டாப்-அப் ஆர்டர்கள்',
    'orders_undelivered': 'Orders Undelivered' if lang == "English" else 'விநியோகிக்கப்படாதவை',
    'cx_cancellations': 'Customer Cancels' if lang == "English" else 'வாடிக்கையாளர் ரத்து',
    'oos_cancellations': 'OOS Undelivered' if lang == "English" else 'OOS ரத்து',
    'total_sales': 'Sale(₹)' if lang == "English" else 'விற்பனை(₹)',
    'overall_fr': 'Overall Fill Rate' if lang == "English" else 'நிறைவேற்றப்பட்ட விகிதம்',
    'otd_700': 'OTD 7:00 AM' if lang == "English" else 'நேரம் 7:00 AM',
    'total_routes': 'Total Routes' if lang == "English" else 'மொத்த வழித்தடங்கள்'
}

# --- MAIN PROCESSING ---
if process_btn:
    with st.spinner("Processing Data..."):
        df_ord = load_file("order_Report_SA_ID")
        df_sku = load_file("order_sku_sales_bb2")
        df_lmd = load_file("iot-rate-card-iot_orderwise")

        if df_ord is None:
            st.error("❌ 'Order Report' not found.")
        else:
            # 2. Data Preparation
            df_ord['sa_name'] = df_ord['sa_name'].fillna('Unknown').astype(str).str.strip().str.upper()
            df_ord['delivery_date'] = pd.to_datetime(df_ord['delivery_date'], errors='coerce').dt.date
            
            df_ord['is_delivered'] = df_ord['order_status'].str.lower().isin(['complete', 'delivered'])
            df_ord['is_sub'] = df_ord['Type'].str.lower() == 'subscription'
            df_ord['is_topup'] = df_ord['Type'].str.lower() == 'topup'
            df_ord['is_oos'] = df_ord['cancellation_reason'].str.contains('OOS|stock', case=False, na=False)
            df_ord['is_cx_cancel'] = df_ord['cancellation_reason'].str.contains('customer', case=False, na=False)

            # 3. Aggregation
            summary = df_ord.groupby(['delivery_date', 'sa_name']).agg(
                total_customers=('member_id', 'nunique'),
                total_orders=('order_id', 'nunique'),
                orders_delivered=('is_delivered', 'sum'),
                sub_orders=('is_sub', 'sum'),
                topup_orders=('is_topup', 'sum'),
                oos_cancellations=('is_oos', 'sum'),
                cx_cancellations=('is_cx_cancel', 'sum'),
                ordered_qty=('OriginalQty', 'sum'),
                delivered_qty=('finalquantity', 'sum')
            ).reset_index()

            # Merges (LMD & Sales)
            if df_lmd is not None:
                df_lmd['sa_name'] = df_lmd['sa_name'].fillna('Unknown').astype(str).str.strip().str.upper()
                df_lmd['dt'] = pd.to_datetime(df_lmd['order_delivered_time'], errors='coerce').dt.date
                lmd_agg = df_lmd.groupby(['dt', 'sa_name']).agg(
                    otd_700=('order_delivered_time', lambda x: (pd.to_datetime(x).dt.time < datetime.strptime('07:00', '%H:%M').time()).mean()),
                    total_routes=('route_id', 'nunique')
                ).reset_index()
                summary = pd.merge(summary, lmd_agg, left_on=['delivery_date', 'sa_name'], right_on=['dt', 'sa_name'], how='left')

            if df_sku is not None:
                df_sku['sa_name'] = df_sku['sa_name'].fillna('Unknown').astype(str).str.strip().str.upper()
                df_sku['delivery_date'] = pd.to_datetime(df_sku['delivery_date'], errors='coerce').dt.date
                sales_agg = df_sku.groupby(['delivery_date', 'sa_name'])['total_sales'].sum().reset_index()
                summary = pd.merge(summary, sales_agg, on=['delivery_date', 'sa_name'], how='left')

            summary['orders_undelivered'] = summary['total_orders'] - summary['orders_delivered']
            summary['overall_fr'] = (summary['delivered_qty'] / summary['ordered_qty']).fillna(0)

            # --- CHARTS SECTION ---
            if show_charts:
                st.subheader("📈 Delivery Performance by Store")
                chart_data = summary.set_index('sa_name')[['orders_delivered', 'orders_undelivered']]
                st.bar_chart(chart_data, color=["#2ecc71", "#e74c3c"]) # Green for Delivered, Red for Undelivered

            # --- DYNAMIC TABLE ---
            available_cols = [col for col in target_cols.keys() if col in summary.columns]
            final_df = summary[available_cols].rename(columns=target_cols).fillna(0)
            
            st.subheader("📑 Data Summary")
            st.dataframe(final_df, use_container_width=True)

            csv = final_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Report", data=csv, file_name="BBD_Performance.csv", mime='text/csv')
