import json
import math
import os
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import Logins_and_Paths as LnP



def search_hits(place_name):
    """
    Return a DataFrame of matching places or POIs for the given name.
    For places this returns the API /places/ results (with 'key' and 'tticodes').
    For POIs this returns the API /pois/ results (with 'id', 'name_primary', 'lat', 'lon', 'places').
    """
    session = requests.Session()
    session.auth = (LnP.ttiplaces_username, LnP.ttiplaces_password)

    try:
        # Page through /places/ until a match is found.
        params = {
            "showcolumns": "name_primary,state,country_code,tticodes",
            "format": "json",
        }
        r = session.get(LnP.places_url, params=params)
        if not r.ok:
            return None, "Error:", r.status_code, r.text

        data = r.json()
        if not data:
            return None, "No data found."

        df = pd.DataFrame(data.values())
        # First, check for exact match, then partial match if none found
        hits_df = df[df["name_primary"].str.lower() == place_name.lower()]
        if hits_df.empty:
            hits_df = df[df["name_primary"].str.contains(place_name, case=False)]

        return hits_df
    except Exception:
        return pd.DataFrame()
    finally:
        session.close()



def main(place_name, place_is_poi, searchable_type, required_keywords = set(), min_rating = 0, max_distance = 0, nearby_poi_type = "", selected_key = None):
    session = requests.Session()
    session.auth = (LnP.ttiplaces_username, LnP.ttiplaces_password)

    property_codes = set()

    if place_is_poi or nearby_poi_type:
        poi_info_df = pd.read_excel(LnP.poi_info_xlsx_path, sheet_name="ACTUAL LAT_LONGS")

    print("Test: main() starts here.\n\n") #/// Test print



    ### STEP 1: Find the key for a chosen place or poi ###
    if not place_is_poi:
        # When selected_key is provided, skip searching by name as we already know what place to use
        if selected_key:
            print("Using provided place key: {}\n\n".format(selected_key)) #/// Test print
            # Get TTI Codes for the selected key
            place_url = LnP.get_place_url(selected_key)
            params = {
                "showcolumns": "tticodes",
                "format": "json"
            }

            # Perform authenticated request
            response = session.get(place_url, params=params)
            if not response.ok:
                return None, f"Error fetching place {selected_key}: {response.status_code} {response.text}"

            raw_data = response.json()
            if not raw_data:
                return None, "No data found."
            place_data = raw_data[selected_key]

            # Get TTICodes
            for code in place_data.get("tticodes", []):
                property_codes.add(int(code))
            print("Property codes: {}\n\n".format(property_codes))
        # Otherwise, page through /places/ until a match is found.
        else:
            params = {
                "showcolumns": "name_primary,tticodes",
                "format": "json",
            }
            r = session.get(LnP.places_url, params=params)
            if not r.ok:
                return None, "Error:", r.status_code, r.text

            data = r.json()
            if not data:
                return None, "No data found."

            df = pd.DataFrame(data.values())
            # First, check for exact match, then partial match if none found
            hits_df = df[df["name_primary"].str.lower() == place_name.lower()]
            if hits_df.empty:
                hits_df = df[df["name_primary"].str.contains(place_name, case=False)]

            if not hits_df.empty:
                print("Found place '{}'".format(hits_df.iloc[0]["name_primary"])) #/// Test print
                for tti_code in hits_df.iloc[0]["tticodes"]: #/// Should I look beyond the first entry?
                    property_codes.add(int(tti_code))
                print("Property codes: {}\n\n".format(property_codes))

            selected_key = hits_df.iloc[0]["key"] if not hits_df.empty else None

        if len(property_codes) == 0:
            return None, "Place not found."
        
        # Now search for POIs of the given type within this place, if applicable
        if nearby_poi_type:
            print("Searching for nearby POIs of type '{}'...".format(nearby_poi_type)) #/// Test print
            params = {
                "showcolumns": "id,name_primary,lat,lon,places",
                # "format": "json", #/// Can't use JSON as it returns an object per line, not a list
            }
            r = session.get(LnP.pois_url, params=params)

            if not r.ok:
                return None, "Error:", r.status_code, r.text

            # data = r.json()
            data = json.loads("[" + r.text.strip()[1:-3] + "\n]")
            if not data:
                return None, "No data found."

            poi_df = pd.DataFrame(data)
            # Ensure POI id types align, merge local POI metadata (has 'POIS ID' and 'POIS Type')
            poi_df["id"] = poi_df["id"].astype(int)
            poi_merged_df = poi_df.merge(
                poi_info_df[["POIS ID", "POIS Type"]],
                left_on="id",
                right_on="POIS ID",
                how="left"
            )

            # Filter by POIS Type in the local sheet and by membership in the selected place
            poi_hits_df = poi_merged_df[
                (poi_merged_df["POIS Type"].fillna("").str.lower() == nearby_poi_type.strip().lower()) &
                (poi_merged_df["places"].apply(lambda places: selected_key in places))
            ]

            if poi_hits_df.empty:
                return None, "No nearby POIs of type '{}' found within place '{}'.".format(nearby_poi_type, place_name)
            else:
                #/// Test print of all found POIs
                for _, row in poi_hits_df.iterrows():
                    poi_id = int(row["id"])
                    poi_longitude = float(row["lon"])
                    poi_latitude = float(row["lat"])
                    print("Found POI '{}' (ID: {}) at lat {}, lon {}".format(row["name_primary"], poi_id, poi_latitude, poi_longitude))
                print("\n")
                
    else:
        # Page through /pois/ until a match is found.
        params = {
            "showcolumns": "id,name_primary,lat,lon,places",
            # "format": "json", #/// Can't use JSON as it returns an object per line, not a list
        }
        r = session.get(LnP.pois_url, params=params)

        if not r.ok:
            return None, "Error:", r.status_code, r.text

        # data = r.json()
        data = json.loads("[" + r.text.strip()[1:-3] + "\n]")
        if not data:
            return None, "No data found."

        df = pd.DataFrame(data)
        # First, check for exact match, then partial match if none found
        hits_df = df[df["name_primary"].str.lower() == place_name.lower()]
        if hits_df.empty:
            hits_df = df[df["name_primary"].str.contains(place_name, case=False)]

        if not hits_df.empty:
            poi_id = float(hits_df.iloc[0]["id"])
            poi_longitude = float(hits_df.iloc[0]["lon"])
            poi_latitude = float(hits_df.iloc[0]["lat"])
            print("Found POI '{}'".format(hits_df.iloc[0]["name_primary"])) #/// Test print
            
            # Get list of TTICodes for a given place
            for parent_place in hits_df.iloc[0]["places"]:
                # Perform authenticated request
                params = {
                    "showcolumns": "tticodes",
                    "format": "json"
                }
                response = session.get(LnP.get_place_url(parent_place), params=params)

                if response.ok:
                    raw_data = response.json()
                    place_data = raw_data[parent_place]

                    # Get TTICodes
                    for code in place_data.get("tticodes", []):
                        property_codes.add(int(code))
                else:
                    print(f"Error fetching place {parent_place}: {response.status_code} {response.text}")
            print(property_codes)
            print("\n")

    if len(property_codes) == 0:
        return None, "POI not found."
    
    session.close()



    ### STEP 2: Get info for each property, filtered by type and rating (if applicable) ###
    # Load in info sheet
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "properties.parquet")

    use_cols = ["TTICODE", "GIATA ID", "NAME", "CITY", "LOCALE", "COUNTRY", "LATITUDE", "LONGITUDE", "DEFAULT_RATING", "Searchable Property Type"] # Need to delete cache in order to change columns

    try:
        # If cache is newer than the Excel file, read the parquet cache
        if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= os.path.getmtime(LnP.property_info_xlsx_path):
            property_df = pd.read_parquet(cache_path)
        else:
            # Read only selected columns from each sheet, then cache as parquet for next runs
            properties_a_k_df = pd.read_excel(LnP.property_info_xlsx_path, sheet_name="CNTRIES A_K", engine="openpyxl", usecols=use_cols)
            properties_l_z_df = pd.read_excel(LnP.property_info_xlsx_path, sheet_name="CNTRIES L_Z", engine="openpyxl", usecols=use_cols)
            property_df = pd.concat([properties_a_k_df, properties_l_z_df], ignore_index=True)
            # Write a compact, fast-to-read cache
            property_df.to_parquet(cache_path, index=False)
    except Exception:
        # Fallback: full read if selective read of cache fails
        properties_a_k_df = pd.read_excel(LnP.property_info_xlsx_path, sheet_name="CNTRIES A_K", engine="openpyxl")
        properties_l_z_df = pd.read_excel(LnP.property_info_xlsx_path, sheet_name="CNTRIES L_Z", engine="openpyxl")
        property_df = pd.concat([properties_a_k_df, properties_l_z_df], axis=0)
    print("Property DataFrame length: {}\n".format(len(property_df.index)))

    # Get info for each property
    if "TTICODE" in property_df.columns:
        filtered_df = property_df[
            (property_df["Searchable Property Type"].astype(str).str.contains(searchable_type, case=False, na=False)) &
            (property_df["TTICODE"].isin(property_codes)) &
            (property_df["DEFAULT_RATING"].fillna(0) >= min_rating)
        ]
        print(filtered_df.head())
        print("Filtered length: {}\n\n".format(len(filtered_df.index)))
    else:
        return None, "Property data import failed."
    


    ### STEP 3: Import facts for each property, and filter as required ###
    # --- Load the CSV with FACT IDs + keywords ---
    df = pd.read_csv(LnP.property_facts_csv_path, header=[0,1])

    # Create a mapping of FACT ID to keywords
    fact_keywords = {}

    for _, row in df.iterrows():
        if not math.isnan(row["FACT ID"].iloc[0]):
            fid = str(int(row["FACT ID"].iloc[0])).strip()   # Normalize FACT ID to string
            keywords = {
                col[1] for col in df.columns[1:]   # Skip "FACT ID" col
                if str(row[col]).lower() == "x"
            }
            fact_keywords[fid] = keywords
    
    # --- Get the fact IDs from the XML ---
    # Cache facts locally and fetch missing GIATA IDs in parallel to speed up repeated runs
    os.makedirs(cache_dir, exist_ok=True)
    facts_cache_path = os.path.join(cache_dir, "giata_facts.parquet")
    if os.path.exists(facts_cache_path):
        facts_cache_df = pd.read_parquet(facts_cache_path)
        # Ensure GIATA_ID dtype matches filtered_df values
        facts_cache = {int(r["GIATA_ID"]): set(r["KEYWORDS"].split("||")) if r["KEYWORDS"] else set() for _, r in facts_cache_df.iterrows()}
    else:
        facts_cache = {}

    giata_ids = [int(x) for x in filtered_df["GIATA ID"].tolist()]
    ids_to_fetch = [gid for gid in giata_ids if gid not in facts_cache]

    # Prepare session with retries
    session_f = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    session_f.mount("https://", HTTPAdapter(max_retries=retries))

    def fetch_giata(gid):
        try:
            url = LnP.get_factsheet_url(gid)
            resp = session_f.get(url, auth=(LnP.giata_username, LnP.giata_password), timeout=15)
            if not resp.ok:
                return gid, set()
            root = ET.fromstring(resp.content)
            fact_ids = [fact.attrib["id"] for fact in root.findall(".//fact") if "id" in fact.attrib]
            keywords = set()
            for fid in fact_ids:
                if fid in fact_keywords:
                    keywords |= fact_keywords[fid]
            return gid, keywords
        except Exception:
            return gid, set()

    # Fetch missing facts in parallel
    if ids_to_fetch:
        max_workers = min(12, max(2, len(ids_to_fetch)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(fetch_giata, gid): gid for gid in ids_to_fetch}
            for fut in concurrent.futures.as_completed(futures):
                gid, keywords = fut.result()
                facts_cache[gid] = keywords

        # Persist cache as parquet for future runs (serialize sets as "||" joined string)
        cache_rows = [{"GIATA_ID": k, "KEYWORDS": "||".join(sorted(v))} for k, v in facts_cache.items()]
        pd.DataFrame(cache_rows).to_parquet(facts_cache_path, index=False)

    session_f.close()

    # Build the list of matching keyword sets in the same order as filtered_df
    all_matching_keywords = [facts_cache.get(int(gid), set()) for gid in filtered_df["GIATA ID"]]

    # Apply required_keywords filter
    mask = [required_keywords.issubset(keywords) for keywords in all_matching_keywords]

    # Convert sets to comma-separated, title-cased strings
    filtered_df["KEYWORDS"] = [
        ", ".join(sorted([kw.title() for kw in keywords])) if keywords else ""
        for keywords in all_matching_keywords
    ]
    
    # Filter out rows that don't match all required keywords
    if len(required_keywords) > 0:
        filtered_df = filtered_df[mask].reset_index(drop=True)
        print("DF filtered by facts:\n{}\n\n".format(filtered_df))



    ### STEP 4: Sort by distance to POI if applicable, and filter if requested ###
    if place_is_poi or nearby_poi_type: # Calculate distance from POI (Haversine formula)
        def haversine(lat1, lon1, lat2, lon2):
            # Convert decimal degrees to radians
            lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
            # Haversine formula
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
            c = 2 * math.asin(math.sqrt(a))
            r = 6371  # Radius of earth in kilometers. Use 3956 for miles
            return c * r

        # Get more accurate lat/long from provided spreadsheet
        if place_is_poi:
            if (
                poi_id in poi_info_df["POIS ID"].values and
                not math.isnan(poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lat"]) and
                not math.isnan(poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lon"])
            ):
                print("Using verified POI lat/long.")
                print("Old lat/long: {}, {}".format(poi_latitude, poi_longitude))
                poi_latitude = poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lat"]
                poi_longitude = poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lon"]
                print("New lat/long: {}, {}\n\n".format(poi_latitude, poi_longitude))
            else:
                print("Using POI lat/long from API.\n\n")

            # Apply distance calculation
            filtered_df["DISTANCE (km)"] = filtered_df.apply(lambda row: haversine(poi_latitude, poi_longitude, row["LATITUDE"], row["LONGITUDE"]), axis=1) # formatted to 2 decimal places
            filtered_df.sort_values(by="DISTANCE (km)", inplace=True)

            print(filtered_df.head())
            print("Sorted by distance to POI.\n\n")
        else: # nearby_poi_type
            # Get list of POIs of the given type within the selected place
            poi_info = []
            for _, row in poi_hits_df.iterrows():
                poi_id = int(row["id"])
                poi_name = row["name_primary"]
                # Use verified lat/lon if available
                if (
                    poi_id in poi_info_df["POIS ID"].values and
                    not math.isnan(poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lat"]) and
                    not math.isnan(poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lon"])
                ):
                    lat = poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lat"]
                    lon = poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lon"]
                else:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
                poi_info.append({"id": poi_id, "name": poi_name, "lat": lat, "lon": lon})

            poi_lists = []
            closest_poi_names = []
            nearest_distances = []

            for _, prop in filtered_df.iterrows():
                prop_lat = prop["LATITUDE"]
                prop_lon = prop["LONGITUDE"]

                # Compute all distances to POIs
                distances = [
                    (poi["name"], haversine(poi["lat"], poi["lon"], prop_lat, prop_lon))
                    for poi in poi_info
                ]
                # Sort by numeric distance
                distances.sort(key=lambda x: x[1])

                # If a max_distance was provided, trim the list
                if max_distance and max_distance > 0:
                    distances = [item for item in distances if item[1] <= max_distance]

                # Build a readable string listing POIs with distances
                if distances:
                    poi_list_str = ", ".join(f"{name} ({dist:.2f} km)" for name, dist in distances)
                    closest_name = distances[0][0]
                    closest_dist = distances[0][1]
                else:
                    poi_list_str = ""
                    closest_name = ""
                    closest_dist = float("nan")

                poi_lists.append(poi_list_str)
                closest_poi_names.append(closest_name)
                nearest_distances.append(closest_dist)

            filtered_df["NEARBY POI LIST"] = poi_lists
            filtered_df["CLOSEST POI"] = closest_poi_names
            # Keep numeric distances for correct numeric sorting/filtering
            filtered_df["DISTANCE (km)"] = nearest_distances

            # Sort numerically by nearest distance, putting rows with no POIs last
            filtered_df.sort_values(by="DISTANCE (km)", inplace=True, na_position="last")

            print(filtered_df.head())
            print("Built full POI lists and sorted by nearest POI.\n\n")

        # Filter by minimum distance if specified
        if max_distance > 0:
            filtered_df = filtered_df[filtered_df["DISTANCE (km)"] <= max_distance]
            print(filtered_df.head())
            print("Filtered by maximum distance of {} km.\n\n".format(max_distance))
        
        # Format distance column for display
        filtered_df["DISTANCE (km)"] = filtered_df["DISTANCE (km)"].map(lambda v: f"{v:.2f}" if pd.notnull(v) else "")



    ### STEP 5: Filter down to 20 ###
    if len(filtered_df.index) > 20:
        filtered_df = filtered_df.head(20) #/// Should I be ordering the places in any particular way?


    
    ### STEP 6: Tidy up data before returning ###
    # Drop columns not needed in output, and rename RATING column
    filtered_df.drop(columns=["GIATA ID", "LATITUDE", "LONGITUDE", "ACCURACY", "CHAINS", "PRIMARY_PROPERTY_TYPE", "Unnamed: 12", "Include / Exclude Ind", "Searchable Property Type"],
                     inplace=True,
                     errors='ignore')
    filtered_df.rename(columns={"DEFAULT_RATING": "RATING"}, inplace=True)
    return filtered_df, ""



if __name__ == "__main__":
    place_name = "Edinburgh" # Name of place or POI to search for
    place_is_poi = False # True if searching for a POI, False for a place
    searchable_type = "HOTEL" # APARTHOTEL, APARTMENTS, B &B, CLUB RESORT, COUNTRYSIDE HOTEL, GUEST HOUSE, HOLIDAY COMPLEX, HOSTEL, HOTEL, RANCH, RESORT, Studios, VILLA
    required_keywords = set() # Set {} of keyword, e.g. ADULTS, BEACH, SKI CLUB, SPA, GOLF, FAMILY, NLIFE, KIDS, WSPORT, ACCESSIBILITY, ALLINCL, POOL, TENNIS, GYM, BOUTIQUE
    min_rating = 0 # 0 to 5
    max_distance = 3.5 # in km, 0 for no maximum
    nearby_poi_type = "Rail" # Filter for all POIs of a given type within the provided place: Airport Terminal, Beach, Cruise, Education, Golf, Healthcare, Landmark, Mine, Rail, Sport, Venues

#     place_name = "Leicester Square" # Name of place or POI to search for
#     place_is_poi = True # True if searching for a POI, False for a place
#     searchable_type = "HOTEL" # APARTHOTEL, APARTMENTS, B &B, CLUB RESORT, COUNTRYSIDE HOTEL, GUEST HOUSE, HOLIDAY COMPLEX, HOSTEL, HOTEL, RANCH, RESORT, Studios, VILLA
#     required_keywords = set() # Set {} of keyword, e.g. ADULTS, BEACH, SKI CLUB, SPA, GOLF, FAMILY, NLIFE, KIDS, WSPORT, ACCESSIBILITY, ALLINCL, POOL, TENNIS, GYM, BOUTIQUE
#     min_rating = 0 # 0 to 5
#     max_distance = 500 # in km, 0 for no maximum
#     nearby_poi_type = "" # Filter for all POIs of a given type within the provided place: Airport Terminal, Beach, Cruise, Education, Golf, Healthcare, Landmark, Mine, Rail, Sport, Venues

    selected_key = None
    # selected_key = "aaa3a48f4dee7334dc4b8f8038d61231" # Provide a specific place key to skip searching by name, or None to search by name. Only works for places, not POIs
    
    df, message = main(place_name, place_is_poi, searchable_type, required_keywords, min_rating, max_distance, nearby_poi_type, selected_key)
    if not message:
        # Save to CSV
        df.to_csv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "Output", "{} Properties.csv".format(place_name)), index=False, encoding="utf-8-sig")
        print("Saved '{} Properties.csv' with {} entries.\n\n".format(place_name, len(df.index)))
    else:
        print(message)