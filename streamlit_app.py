import streamlit as st
import pandas as pd
import numpy as np
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

st.set_page_config(page_title="Last Mile Router", layout="wide")

def solve_vrp(group_df, vehicle_capacity_kg=40, weight_per_order=1.5):
    """Core routing engine using Google OR-Tools."""
    if len(group_df) == 0: return pd.DataFrame()

    # Note: In production, replace this with actual Lat/Long from a Geocoding API
    # Here we simulate coordinates based on Pincode for spatial clustering
    group_df['lat'] = 12.97 + (group_df['Pincode'] % 100) * 0.01 + (group_df['order_id'] % 100) * 0.0001
    group_df['lon'] = 77.59 + (group_df['Pincode'] % 100) * 0.01 + (group_df['order_id'] % 77) * 0.0001

    depot_lat, depot_lon = group_df['lat'].mean(), group_df['lon'].mean()
    locations = [[depot_lat, depot_lon]] + group_df[['lat', 'lon']].values.tolist()
    order_ids = ["DEPOT"] + group_df['order_id'].tolist()
    
    num_locations = len(locations)
    weights = [0] + [int(weight_per_order * 10)] * (num_locations - 1)
    max_cap_units = int(vehicle_capacity_kg * 10)
    
    # Estimate required vehicles
    num_vehicles = int(np.ceil((len(group_df) * weight_per_order) / vehicle_capacity_kg)) + 2
    
    # Distance Matrix (Euclidean approximation)
    dist_matrix = [[int(np.hypot(l1[0]-l2[0], l1[1]-l2[1]) * 100000) for l2 in locations] for l1 in locations]

    # Solver
    manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, 0)
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
    search_params.time_limit.seconds = 2

    solution = routing.SolveWithParameters(search_params)

    results = []
    if solution:
        for v_id in range(num_vehicles):
            index = routing.Start(v_id)
            seq = 1
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:
                    results.append({
                        'Order_ID': order_ids[node],
                        'CEE_ID': f"{group_df['sa_name'].iloc[0]}_CEE_{v_id+1}",
                        'Sequence': seq
                    })
                    seq += 1
                index = solution.Value(routing.NextVar(index))
    return pd.DataFrame(results)

st.title("🚚 Last-Mile Delivery Optimizer")
uploaded_file = st.file_uploader("Upload Order Report", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    df = df[df['order_status'] != 'cancelled']
    
    st.sidebar.header("Constraints")
    cap = st.sidebar.number_input("Vehicle Capacity (kg)", value=40)
    w_order = st.sidebar.number_input("Avg Order Weight (kg)", value=1.5)
    
    if st.button("Generate Optimized Routes"):
        all_routes = []
        with st.spinner("Calculating routes per Service Area..."):
            for sa, group in df.groupby('sa_name'):
                sa_routes = solve_vrp(group, cap, w_order)
                all_routes.append(sa_routes)
        
        final_routes = pd.concat(all_routes)
        output = pd.merge(final_routes, df[['order_id', 'fullName', 'address', 'sa_name']], 
                          left_on='Order_ID', right_on='order_id').drop('order_id', axis=1)
        
        st.success(f"Optimized {len(output)} orders across {output['CEE_ID'].nunique()} CEEs.")
        st.dataframe(output)
        
        csv = output.to_csv(index=False).encode('utf-8')
        st.download_button("Download Route Plan", csv, "optimized_routes.csv", "text/csv")
