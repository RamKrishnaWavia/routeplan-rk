import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import datetime

# --- PAGE SETUP ---
st.set_page_config(page_title="BBD Daily Summary", layout="wide")
st.title("🚀 BBD Daily Summary Dashboard")

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

# --- MAIN PROCESSING LOGIC ---
if st.button("Generate Complete Dashboard"):
    with st.spinner("Processing files and calculating metrics..."):
        # 1. Load Datasets
        df_ord = load_file("order_Report_SA_ID")
        df_sku = load_file("order_sku_sales_bb2")
        df_lmd = load_file("iot-rate-card-iot_orderwise")

        if df_ord is None:
            st.error("❌ Critical Error: 'order_Report_SA_ID' file not found.")
        else:
            # --- DATA CLEANING ---
            # Standardize Store Names and Dates to ensure merge works
            df_ord['sa_name'] = df_ord['sa_name'].fillna('Unknown').astype(str).str.strip().str.upper()
            df_ord['delivery_date'] = pd.to_datetime(df_ord['delivery_date'], errors='coerce').dt.normalize()
            
            # Convert numeric columns
            num_cols = ['OriginalQty', 'finalquantity', 'OriginalOrderValue', 'FinalOrderValue']
            for col in num_cols:
                df_ord[col] = pd.to_numeric(df_ord[col], errors='coerce').fillna(0)

            # Pre-calculate flags (Avoids broadcasting errors in groupby)
            df_ord['is_delivered'] = df_ord['order_status'].str.lower().isin(['complete', 'delivered'])
            df_ord['is_sub'] = df_ord['Type'].str.lower() == 'subscription'
            df_ord['is_topup'] = df_ord['Type'].str.lower() == 'topup'
            df_ord['is_milk'] = df_ord['Milk / NM'].str.lower() == 'milk'
            df_ord['is_non_milk'] = df_ord['Milk / NM'].str.lower() == 'non-milk'
            df_ord['is_oos'] = df_ord['cancellation_reason'].str.contains('OOS|stock', case=False, na=False)
            df_ord['is_cx_cancel'] = df_ord['cancellation_reason'].str.contains('customer', case=False, na=False)

            # --- 1. CORE AGGREGATION ---
            summary = df_ord.groupby(['delivery_date', 'sa_name']).agg(
                total_customers=('member_id', 'nunique'),
                total_orders=('order_id', 'nunique'),
                orders_delivered=('is_delivered', 'sum'), # Boolean sum
                sub_orders=('is_sub', 'sum'),
                topup_orders=('is_topup', 'sum'),
                oos_cancellations=('is_oos', 'sum'),
                cx_cancellations=('is_cx_cancel', 'sum'),
                ordered_qty=('OriginalQty', 'sum'),
                delivered_qty=('finalquantity', 'sum'),
                # Weighted Qty calculations using masking
                milk_qty_ordered=('OriginalQty', lambda x: df_ord.loc[x.index, 'is_milk'].multiply(df_ord.loc[x.index, 'OriginalQty']).sum()),
                milk_qty_delivered=('finalquantity', lambda x: df_ord.loc[x.index, 'is_milk'].multiply(df_ord.loc[x.index, 'finalquantity']).sum()),
                nmilk_qty_ordered=('OriginalQty', lambda x: df_ord.loc[x.index, 'is_non_milk'].multiply(df_ord.loc[x.index, 'OriginalQty']).sum()),
                nmilk_qty_delivered=('finalquantity', lambda x: df_ord.loc[x.index, 'is_non_milk'].multiply(df_ord.loc[x.index, 'finalquantity']).sum()),
                sub_qty=('OriginalQty', lambda x: df_ord.loc[x.index, 'is_sub'].multiply(df_ord.loc[x.index, 'OriginalQty']).sum())
            ).reset_index()

            # --- 2. LOGISTICS & OTD (From LMD Report) ---
            if df_lmd is not None:
                df_lmd['sa_name'] = df_lmd['sa_name'].fillna('Unknown').astype(str).str.strip().str.upper()
                df_lmd['dt'] = pd.to_datetime(df_lmd['order_delivered_time'], errors='coerce').dt.normalize()
                
                # Convert time for OTD
                def check_otd(series, time_str):
                    limit = datetime.strptime(time_str, '%H:%M').time()
                    times = pd.to_datetime(series, errors='coerce').dt.time
                    return (times < limit).mean()

                lmd_agg = df_lmd.groupby(['dt', 'sa_name']).agg(
                    otd_700=('order_delivered_time', lambda x: check_otd(x, '07:00')),
                    otd_730=('order_delivered_time', lambda x: check_otd(x, '07:30')),
                    otd_800=('order_delivered_time', lambda x: check_otd(x, '08:00')),
                    total_routes=('route_id', 'nunique'),
                    total_weight=('weight', 'sum')
                ).reset_index()
                summary = pd.merge(summary, lmd_agg, left_on=['delivery_date', 'sa_name'], right_on=['dt', 'sa_name'], how='left')

            # --- 3. SALES (From SKU Report) ---
            if df_sku is not None:
                df_sku['sa_name'] = df_sku['sa_name'].fillna('Unknown').astype(str).str.strip().str.upper()
                df_sku['delivery_date'] = pd.to_datetime(df_sku['delivery_date'], errors='coerce').dt.normalize()
                sales_agg = df_sku.groupby(['delivery_date', 'sa_name'])['total_sales'].sum().reset_index()
                summary = pd.merge(summary, sales_agg, on=['delivery_date', 'sa_name'], how='left')

            # --- 4. CALCULATED RATIOS ---
            summary['orders_undelivered'] = summary['total_orders'] - summary['orders_delivered']
            summary['abv'] = (summary['total_sales'] / summary['orders_delivered']).replace([np.inf, -np.inf], 0).fillna(0)
            summary['abq'] = (summary['delivered_qty'] / summary['orders_delivered']).replace([np.inf, -np.inf], 0).fillna(0)
            summary['fr_milk'] = (summary['milk_qty_delivered'] / summary['milk_qty_ordered']).fillna(0)
            summary['fr_non_milk'] = (summary['nmilk_qty_delivered'] / summary['nmilk_qty_ordered']).fillna(0)
            summary['overall_fr'] = (summary['delivered_qty'] / summary['ordered_qty']).fillna(0)
            
            if 'total_weight' in summary.columns:
                summary['weight_per_route'] = summary['total_weight'] / summary['total_routes']
                summary['weight_per_order'] = summary['total_weight'] / summary['orders_delivered']

            # --- FINAL FORMATTING (KeyError Prevention) ---
            target_cols = {
                'delivery_date': 'Date', 'sa_name': 'Store Name',
                'total_customers': 'Total Ordered Customers (Unique)', 'total_orders': 'Total Orders',
                'orders_delivered': 'Orders Delivered', 'sub_orders': 'Subscription Orders',
                'topup_orders': 'Top-up Orders', 'orders_undelivered': 'Orders Undelivered',
                'cx_cancellations': 'Cancelled Orders by Customer', 'oos_cancellations': 'Undelivered Orders Due to OOS',
                'ordered_qty': 'Total Ordered Quantity', 'sub_qty': 'Subscription Quantity',
                'milk_qty_ordered': 'Milk Qty (Ord)', 'milk_qty_delivered': 'Milk Qty (Del)',
                'nmilk_qty_ordered': 'NM Qty (Ord)', 'nmilk_qty_delivered': 'NM Qty (Del)',
                'otd_700': 'OTD 7:00 AM', 'otd_730': 'OTD 7:30 AM', 'otd_800': 'OTD 8:00 AM',
                'abv': 'ABV', 'abq': 'ABQ', 'overall_fr': 'Overall Fill Rate', 'total_sales': 'Sale(₹)',
                'total_routes': 'Routes', 'weight_per_route': 'Wt/Route'
            }

            # Only select columns that actually ended up in the dataframe
            final_selection = [col for col in target_cols.keys() if col in summary.columns]
            final_df = summary[final_selection].rename(columns=target_cols).fillna(0)

            # Display
            st.success("✅ Dashboard Generated")
            st.dataframe(final_df, use_container_width=True)
            
            csv = final_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", data=csv, file_name="BBD_Summary.csv", mime="text/csv")
