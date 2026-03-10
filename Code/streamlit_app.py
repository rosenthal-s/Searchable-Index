import pandas as pd
import streamlit as st
import Main



### STYLES ###

css = """
.st-key-input_container {
    background-color: rgba(78, 184, 165, 1);
    padding: 30px;
}
.st-key-output_container, .st-key-output_container_2 {
    background-color: rgba(79, 126, 203, 1);
    padding: 30px;
}
"""

st.html(f"<style>{css}</style>")



### TITLE AND HEADER ###

st.set_page_config(page_title="Find Properties Near Place or POI", layout="wide")

st.markdown("""
    <div style="background-color: #333333; padding: 17.5px; border-radius: 5px; margin-bottom: 37.5px;">
        <h1 style="color: white; margin: 0; text-align: center;">Find Properties Near Place or POI</h1>
    </div>
    """, unsafe_allow_html=True)



### INPUT ELEMENTS ###

with st.container(key="input_container"):
    location_name = st.text_input("Place or POI name", "").strip()

    place_or_poi = st.radio("Type", ("Any", "Place", "POI"), horizontal=True)
    location_is_place = not (place_or_poi == "POI")
    location_is_poi = not (place_or_poi == "Place")

    # Clear previous candidate options when user edits location_name or place_or_poi
    if st.session_state.get("last_location_name") != location_name or st.session_state.get("last_location_type") != place_or_poi:
        st.session_state.pop("candidate_options", None)
        st.session_state.pop("candidate_choice_idx", None)
        st.session_state.pop("selected_hit_key", None)
        st.session_state["last_location_name"] = location_name
        st.session_state["last_location_type"] = place_or_poi

    type_options = [
        "APARTHOTEL", "APARTMENTS", "B &B", "CABINS", "CLUB RESORT", "COUNTRYSIDE HOTEL", "GUEST HOUSE", "HACIENDA",
        "HOLIDAY COMPLEX", "HOLIDAY RENTAL", "HOSTEL", "HOTEL", "RANCH", "RESORT", "STUDIOS", "VILLA"
    ]
    type_default_index = type_options.index("HOTEL") if "HOTEL" in type_options else 0
    searchable_type = st.selectbox("Searchable type", type_options, index=type_default_index)

    keywords_options = [
        "ACCESSIBILITY","ADULTS","ALLINCL","BEACH","BOUTIQUE","BUSINESSHOTEL","CARPARK",
        "FAMILY","GOLF","GYM","KIDS","NLIFE","POOL","SKI CLUB","SPA","TENNIS","WSPORT"
    ]
    selected_keywords = st.multiselect("Required keywords", options=keywords_options)
    required_keywords = {k.strip().upper() for k in selected_keywords}

    min_rating = st.number_input("Minimum rating (0–5)", min_value=0.0, max_value=5.0, value=0.0, step=0.5, format="%g")

    max_distance = st.number_input("Maximum distance (km), 0 = no limit", min_value=0.0, value=0.0, step=0.1, format="%g")

    nearby_poi_options = [
        "", "Airport Terminal", "Beach", "Cruise", "Education", "Golf",
        "Healthcare", "Landmark", "Mine", "Rail", "Sport", "Venues"
    ]
    nearby_poi_type = st.selectbox("Nearby POI type (only used when searching for a place)", nearby_poi_options, index=0, disabled=not location_is_place).strip()



### RUNNING AND OUTPUT ###

with st.container(key="output_container"):
    def run_main(selected_key=None, location_type=None):
        if location_type:
            is_poi = location_type == "POI"
        else:
            is_poi = location_is_poi

        df, message = Main.main(
            location_name,
            is_poi,
            searchable_type.strip().upper() if searchable_type else "",
            required_keywords,
            float(min_rating),
            float(max_distance),
            nearby_poi_type if location_is_place else "",
            selected_key
        )
        if message:
            st.error(message)
        else:
            if df is not None and not df.empty:
                st.markdown("<h5 style='background-color: rgba(154, 185, 90, 1); color: green; padding: 10.5px 10px 10px 12.5px; margin-top: 10px; margin-bottom: 5px;'>Finished - results below:</h5>", unsafe_allow_html=True)
                st.dataframe(df)
                st.download_button(
                    "Download CSV",
                    data=df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{location_name} Properties.csv",
                    mime="text/csv"
                )
            else:
                st.warning("Finished but no results were returned.")



    if not (st.session_state.get("awaiting_confirmation") and st.session_state.get("candidate_options")):
        if st.button("Run", disabled=not location_name):
            with st.spinner("Running - this may take a while..."):
                try:
                    location_hits, error_message = Main.search_hits(location_name, location_is_place, location_is_poi)
                    print(error_message)

                    # Build display labels
                    options = [
                        (
                            row["key"],
                            f"{row.get('name_primary','')} - {', '.join([p for p in (row.get('state',''), row.get('country_code','')) if p])}",
                            row["Type"]
                        )
                        for _, row in location_hits.iterrows()
                    ] if location_hits is not None and not location_hits.empty else []

                    if len(options) == 1:
                        run_main(options[0][0], options[0][2])
                    elif len(options) > 1:
                        # Persist options and enter "awaiting confirmation" state
                        st.session_state["candidate_options"] = options
                        st.session_state["awaiting_confirmation"] = True
                        st.rerun()
                    else:
                        run_main() # No matches, run without selected_key
                except Exception as e:
                    st.exception(e)

    # Render candidate-selection UI outside the Run branch so it survives reruns
    else:
        options = st.session_state["candidate_options"]
        labels = [label for _, label, _ in options]
        st.selectbox(
            "Multiple matches found - pick one",
            list(range(len(labels))),
            format_func=lambda i: labels[i],
            key="candidate_choice_idx"
        )
        if st.button("Confirm Location and Run"):
            with st.spinner("Running - this may take a while..."):
                idx = st.session_state.get("candidate_choice_idx", 0)
                print(f"\n\nUser selected option index: {idx}\nUser selected key: {options[idx][0]}\nLocation type: {options[idx][2]}\n\n")
                selected_key = options[idx][0]
                location_type = options[idx][2]
                run_main(selected_key, location_type)



# Run with 'python -m streamlit run "streamlit_app.py"' from the Code folder