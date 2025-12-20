import streamlit as st
import pandas as pd
import numpy as np
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# --- ROUTING ENGINE ---
def solve_vrp(group_df, capacity_kg=40, weight_per_order=1.5):
    """Core logic to solve routing for a specific cluster."""
    if len(group_df) == 0: return pd.DataFrame()

    # Lat/Lon Simulation based on Pincode and Order ID for spatial grouping
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

    def distance_callback(from_index, to_index):
        return dist_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    def demand_callback(from_index):
        return weights[manager.IndexToNode(from_index)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [max_cap_units]*num_vehicles, True, 'Capacity')

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.time_limit.seconds = 1

    solution = routing.SolveWithParameters(search_params)
    results = []
    if solution:
        for v_id in range(num_vehicles):
            index = routing.Start(v_id)
            seq = 1
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:
                    results.append({'Order_ID': order_ids[node], 'CEE_ID': f"CEE_{v_id+1}", 'Sequence': seq})
                    seq += 1
                index = solution.Value(routing.NextVar(index))
    return pd.DataFrame(results)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Master Delivery Router", layout="wide")
st.title("🚛 Automated Master Delivery Router")
st.markdown("This tool generates optimized routes for all Cities and Stores automatically.")

uploaded_file = st.file_uploader("Upload Order Report (CSV)", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    df = df[df['order_status'] != 'cancelled'] # Exclude cancelled orders
    
    if st.button("Generate Master Route Plan"):
        master_results = []
        progress_bar = st.progress(0)
        
        # Get unique combinations of City and Store
        clusters = df.groupby(['city', 'dc_name'])
        total_clusters = len(clusters)
        
        for i, ((city, store), cluster_df) in enumerate(clusters):
            # Process each Service Area within the Store
            for sa, sa_df in cluster_df.groupby('sa_name'):
                sa_plan = solve_vrp(sa_df)
                if not sa_plan.empty:
                    sa_plan['city'] = city
                    sa_plan['store_name'] = store
                    sa_plan['sa_name'] = sa
                    master_results.append(sa_plan)
            
            progress_bar.progress((i + 1) / total_clusters)

        if master_results:
            master_df = pd.concat(master_results)
            
            # Map back customer information
            final_output = pd.merge(
                master_df, 
                df[['order_id', 'fullName', 'address', 'Pincode']], 
                left_on='Order_ID', right_on='order_id'
            ).drop('order_id', axis=1)

            # Reorder columns for clarity
            cols = ['city', 'store_name', 'sa_name', 'CEE_ID', 'Sequence', 'Order_ID', 'fullName', 'address', 'Pincode']
            final_output = final_output[cols]

            st.success("Master Plan Generated Successfully!")
            st.write(f"Total Routes: {final_output['CEE_ID'].count()} | Total CEEs Assigned: {len(final_output.groupby(['city', 'store_name', 'sa_name', 'CEE_ID']))}")
            
            st.dataframe(final_output)

            # Download Option
            csv = final_output.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Master Delivery Plan (CSV)",
                data=csv,
                file_name="master_delivery_plan.csv",
                mime="text/csv"
            )
