import streamlit as st
import pandas as pd
import numpy as np
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# --- APP CONFIG ---
st.set_page_config(page_title="City & Store Delivery Router", layout="wide")

def solve_vrp(group_df, capacity_kg=40, weight_per_order=1.5):
    """Routing Engine: Groups by SA within the selected Store."""
    group_df = group_df[group_df['order_status'] != 'cancelled'].copy()
    if len(group_df) == 0: return pd.DataFrame()

    # Simulation coordinates for clustering (replace with real geocoding in prod)
    group_df['lat'] = 12.97 + (group_df['Pincode'] % 100) * 0.01 + (group_df['order_id'] % 100) * 0.0001
    group_df['lon'] = 77.59 + (group_df['Pincode'] % 100) * 0.01 + (group_df['order_id'] % 77) * 0.0001

    depot_lat, depot_lon = group_df['lat'].mean(), group_df['lon'].mean()
    locations = [[depot_lat, depot_lon]] + group_df[['lat', 'lon']].values.tolist()
    order_ids = ["DEPOT"] + group_df['order_id'].tolist()
    
    weights = [0] + [int(weight_per_order * 10)] * (len(locations) - 1)
    max_cap_units = int(capacity_kg * 10)
    
    # Estimate vehicles
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

# --- UI LOGIC ---
st.title("🏙️ City & Store Wise Delivery Optimizer")

uploaded_file = st.file_uploader("Upload Delivery Report", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # 1. Select City
    cities = sorted(df['city'].unique())
    selected_city = st.selectbox("Select City", cities)
    
    # 2. Select Store (dc_name)
    city_df = df[df['city'] == selected_city]
    stores = sorted(city_df['dc_name'].unique())
    selected_store = st.selectbox("Select Store (DC Name)", stores)
    
    if st.button("Generate Routing Plan"):
        store_data = city_df[city_df['dc_name'] == selected_store]
        
        # Solving per Service Area inside the store for better local density
        all_store_routes = []
        for sa, sa_group in store_data.groupby('sa_name'):
            sa_plan = solve_vrp(sa_group)
            if not sa_plan.empty:
                sa_plan['sa_name'] = sa
                all_store_routes.append(sa_plan)
        
        if all_store_routes:
            final_plan = pd.concat(all_store_routes)
            # Add customer info back
            final_plan = pd.merge(final_plan, df[['order_id', 'fullName', 'address']], 
                                 left_on='Order_ID', right_on='order_id').drop('order_id', axis=1)
            
            st.success(f"Generated routes for {selected_store} in {selected_city}")
            st.dataframe(final_plan)
            
            csv = final_plan.to_csv(index=False).encode('utf-8')
            st.download_button(f"Download {selected_store} Route CSV", csv, f"{selected_store}_routes.csv", "text/csv")
        else:
            st.warning("No valid orders found for this store.")
