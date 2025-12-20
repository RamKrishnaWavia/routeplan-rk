import streamlit as st
import pandas as pd
import numpy as np
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# --- ROUTING ENGINE ---
def solve_vrp(group_df, capacity_kg=40, weight_per_order=1.5):
    if len(group_df) == 0: return pd.DataFrame()

    # Lat/Lon Simulation based on Pincode
    group_df['lat'] = 12.97 + (group_df['Pincode'] % 100) * 0.01 + (group_df['order_id'] % 100) * 0.0001
    group_df['lon'] = 77.59 + (group_df['Pincode'] % 100) * 0.01 + (group_df['order_id'] % 77) * 0.0001

    depot_lat, depot_lon = group_df['lat'].mean(), group_df['lon'].mean()
    locations = [[depot_lat, depot_lon]] + group_df[['lat', 'lon']].values.tolist()
    order_ids = ["DEPOT"] + group_df['order_id'].tolist()
    
    weights = [0] + [int(weight_per_order * 10)] * (len(locations) - 1)
    max_cap_units = int(capacity_kg * 10)
    num_vehicles = int(np.ceil((len(group_df) * weight_per_order) / capacity_kg)) + 2
    dist_matrix = [[int(np.hypot(l1[0]-l2[0], l1[1]-l2[1]) * 100000) for l2 in locations] for l1 in locations]

    manager = pywrapcp.RoutingIndexManager(len(locations), num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(from_idx, to_idx): return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]
    transit_idx = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    def demand_cb(from_idx): return weights[manager.IndexToNode(from_idx)]
    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [max_cap_units]*num_vehicles, True, 'Capacity')

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.time_limit.seconds = 1

    solution = routing.SolveWithParameters(search_params)
    results = []
    if solution:
        for v_id in range(num_vehicles):
            idx = routing.Start(v_id)
            seq = 1
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                if node != 0:
                    results.append({'Order_ID': order_ids[node], 'Temp_Route': v_id + 1, 'Sequence': seq})
                    seq += 1
                idx = solution.Value(routing.NextVar(idx))
    return pd.DataFrame(results)

# --- APP UI ---
st.set_page_config(page_title="Master Dispatch Router", layout="wide")
st.title("📦 Manual Route Generation Tool - RK Dec 2025")

uploaded_file = st.file_uploader("Upload Order CSV", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    df = df[df['order_status'] != 'cancelled']
    
    if st.button("Generate Master Plan"):
        master_list = []
        # Group by City and Store
        for (city, store), store_df in df.groupby(['city', 'dc_name']):
            store_route_idx = 0
            # Group by SA within Store
            for sa, sa_df in store_df.groupby('sa_name'):
                sa_plan = solve_vrp(sa_df)
                if not sa_plan.empty:
                    # Create continuous route numbers per store
                    r_map = {old: (store_route_idx + i + 1) for i, old in enumerate(sa_plan['Temp_Route'].unique())}
                    sa_plan['Route_Number'] = sa_plan['Temp_Route'].map(r_map)
                    sa_plan['CEE_ID'] = sa_plan['Route_Number'].apply(lambda x: f"{store}_CEE_{x}")
                    
                    sa_plan['city'], sa_plan['store_name'], sa_plan['sa_name'] = city, store, sa
                    master_list.append(sa_plan)
                    store_route_idx += len(r_map)

        final_df = pd.concat(master_list)
        final_df = pd.merge(final_df, df[['order_id', 'fullName', 'address']], left_on='Order_ID', right_on='order_id').drop('order_id', axis=1)
        
        # UI Display
        st.success("Plan Created: Use 'Route_Number' to group trucks per store.")
        st.dataframe(final_df[['city', 'store_name', 'Route_Number', 'CEE_ID', 'sa_name', 'Sequence', 'fullName', 'address']])
        
        csv = final_df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Master Plan", csv, "master_delivery_plan.csv", "text/csv")
