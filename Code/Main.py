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



def get_property_data(url, params, session, location_is_poi):
    try:
        # Perform authenticated request
        response = session.get(url, params=params)
        if not response.ok:
            return None, f"Error fetching data: {response.status_code} {response.text}"
        
        # Place pages are formatted with correct JSON, but POI pages return with some messed up formatting so need to be parsed differently
        if not location_is_poi:
            data = response.json()
        else:
            data = json.loads("[" + response.text.strip()[1:-3] + "\n]")

        if not data:
            return None, "No data found."
        else:
            return data, ""
    except Exception as e:
        return None, repr(e)



def search_hits(location_name, is_place, is_poi):
    """
    Return a DataFrame of matching locations for the given name.
    For places this returns the API /places/ results (with name, state and country).
    For POIs this returns the API /pois/ results (with name and country).
    """
    session = requests.Session()
    session.auth = (LnP.ttiplaces_username, LnP.ttiplaces_password)

    print("\n\n\nTEST PRINT: search_hits() starts here.\n") #/// Test print

    try:
        place_hits_df = None
        poi_hits_df   = None
        place_inexact = False
        poi_inexact   = False

        # Page through /places/ to find relevant matches.
        if is_place:
            place_params = {
                "showcolumns": "name_primary,state,country_code",
                "format": "json",
            }
            place_data, error = get_property_data(LnP.places_url, place_params, session, False)
            if error:
                return place_data, f"Error getting place data: {error}"

            place_df = pd.DataFrame(place_data.values())
            # First, check for exact matches, then partial matches if none found
            place_hits_df = place_df[place_df["name_primary"].str.lower() == location_name.lower()].copy()
            if place_hits_df.empty:
                place_hits_df = place_df[place_df["name_primary"].str.contains(location_name, case=False, regex=False)]
                place_inexact = True

            place_hits_df["Type"] = "Place" # Add a column to identify these locations as places
            
#             print("Place hits:\n{}\n".format(place_hits_df.to_string(index=False))) ###

            if not is_poi:
                return place_hits_df, ""



        # Page through /pois/ to find relevant matches.
        if is_poi:
            poi_params = {
                "showcolumns": "name_primary,country_code",
                # "format": "json", #/// Can't use JSON as it returns an object per line, not a list
            }
            poi_data, error = get_property_data(LnP.pois_url, poi_params, session, True)
            if error:
                return poi_data, f"Error getting POI data: {error}"

            poi_df = pd.DataFrame(poi_data)
            # First, check for exact matches, then partial matches if none found
            poi_hits_df = poi_df[poi_df["name_primary"].str.lower() == location_name.lower()]
            if poi_hits_df.empty and (not is_place or place_inexact): # Only search for partial matches in POIs if we didn't find an exact match in places, to avoid overwhelming with irrelevant POI hits
                poi_hits_df = poi_df[poi_df["name_primary"].str.contains(location_name, case=False, regex=False)]
                poi_inexact = True

            poi_hits_df = poi_hits_df.rename(columns={"id": "key"}) # Align with place_hits_df for easier concatenation later
            poi_hits_df["Type"] = "POI" # Add a column to identify these locations as POIs

#             print("POI hits:\n{}\n".format(poi_hits_df.to_string(index=False))) ###

            if not is_place:
                return poi_hits_df, ""


        
#         print("Place_inexact: {}, POI_inexact: {}\n".format(place_inexact, poi_inexact)) ###
        if place_inexact and not poi_inexact: # Only inexact matches found for places, but exact matches found for POIs. Return only POI hits
            return poi_hits_df, ""
        else:
            hits_df = pd.concat([place_hits_df, poi_hits_df], axis=0, ignore_index=True)
            hits_df.fillna("", inplace=True) # Replace NaNs (for non-existent POI states) with empty strings for cleaner display
#             print("Concatenated hits:\n{}\n".format(hits_df.to_string(index=False))) ###
            return hits_df, ""
    except Exception as e:
        return pd.DataFrame(), repr(e)
    finally:
        session.close()



def main(location_name, location_is_poi, searchable_type, required_keywords = set(), min_rating = 0, max_distance = 0, nearby_poi_type = "", selected_key = None):
    session = requests.Session()
    session.auth = (LnP.ttiplaces_username, LnP.ttiplaces_password)

    if location_is_poi or nearby_poi_type:
        poi_info_df = pd.read_excel(LnP.poi_info_xlsx_path, sheet_name="ACTUAL LAT_LONGS")

    print("Test: main() starts here.\n\n") #/// Test print



    ### STEP 1: Find the key for a chosen place or poi, then get a list of property codes in the area ###
    property_codes = set()

    if not location_is_poi:

        # When selected_key is provided, skip searching by name as we already know what place to use
        if selected_key:
            print("Using provided place key: {}\n\n".format(selected_key)) #/// Test print
            place_params = {
                "showcolumns": "tticodes",
                "format": "json"
            }

            # Perform authenticated request
            place_data, message = get_property_data(url=LnP.get_place_url(selected_key), params=place_params, session=session, location_is_poi=False)
            if not place_data:
                return None, message

            # Get TTICodes
            for property_code in place_data[selected_key].get("tticodes", []):
                property_codes.add(int(property_code))
        # Otherwise, page through /places/ until a match is found.
        else:
            place_params = {
                "showcolumns": "name_primary,tticodes",
                "format": "json",
            }
            place_data, message = get_property_data(url=LnP.places_url, params=place_params, session=session, location_is_poi=False)
            if not place_data:
                return None, message

            place_df = pd.DataFrame(place_data.values())
            # First, check for exact match, then partial match if none found
            hits_df = place_df[place_df["name_primary"].str.lower() == location_name.lower()]
            if hits_df.empty:
                hits_df = place_df[place_df["name_primary"].str.contains(location_name, case=False, regex=False)]

            if not hits_df.empty:
#                 print("Found place '{}'".format(hits_df.iloc[0]["name_primary"])) #/// Test print
                for property_code in hits_df.iloc[0]["tticodes"]: #/// Should I look beyond the first entry?
                    property_codes.add(int(property_code))

            selected_key = hits_df.iloc[0]["key"] if not hits_df.empty else None

        if len(property_codes) == 0:
            return None, "Place not found."
        
        # Now search for POIs of the given type within this place, if applicable
        if nearby_poi_type:
#             print("Searching for nearby POIs of type '{}'...".format(nearby_poi_type)) #/// Test print
            poi_params = {
                "showcolumns": "id,name_primary,lat,lon,places",
                # "format": "json", #/// Can't use JSON as it returns an object per line, not a list
            }
            poi_data, message = get_property_data(url=LnP.pois_url, params=poi_params, session=session, location_is_poi=True)
            if not poi_data:
                if message == "No data found.":
                    return None, "No nearby POIs found within place '{}'.".format(location_name)
                return None, message

            poi_df = pd.DataFrame(poi_data)
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
                return None, "No nearby POIs of type '{}' found within place '{}'.".format(nearby_poi_type, location_name)
#             else:
#                 #/// Test print of all found POIs
#                 for _, row in poi_hits_df.iterrows():
#                     poi_id = int(row["id"])
#                     poi_latitude = float(row["lat"])
#                     poi_longitude = float(row["lon"])
#                     print("Found POI '{}' (ID: {}) at lat {}, lon {}".format(row["name_primary"], poi_id, poi_latitude, poi_longitude))
#                 print("\n")
                
    else:
        # When selected_key is provided, skip searching by name as we already know what poi to use
        if selected_key:
#             print("Using provided POI key: {}\n\n".format(selected_key)) #/// Test print
            # Get TTI Codes for the selected key
            poi_url = LnP.get_poi_url(selected_key)
            poi_params = {
                "showcolumns": "id,lat,lon,places",
                # "format": "json", #/// Can't use JSON as it returns an object per line, not a list
            }

            raw_poi_data, message = get_property_data(url=poi_url, params=poi_params, session=session, location_is_poi=True)
            if not raw_poi_data:
                return None, message
            poi_data = raw_poi_data[0]

            poi_id = poi_data["id"]
            poi_latitude = float(poi_data["lat"])
            poi_longitude = float(poi_data["lon"])

            # Get TTICodes
            for parent_place in poi_data["places"]:
                # Perform authenticated request
                parent_place_url = LnP.get_place_url(parent_place)
                parent_place_params = {
                    "showcolumns": "tticodes",
                    "format": "json"
                }
                
                raw_place_data, message = get_property_data(url=parent_place_url, params=parent_place_params, session=session, location_is_poi=False)
                if not raw_place_data:
                    print(f"Error fetching place {parent_place}: {message}")
                else:
                    parent_place_data = raw_place_data[parent_place]
                    # Get TTICodes
                    for property_code in parent_place_data.get("tticodes", []):
                        property_codes.add(int(property_code))
        # Otherwise, page through /pois/ until a match is found.
        else:
            poi_params = {
                "showcolumns": "id,name_primary,lat,lon,places",
                # "format": "json", #/// Can't use JSON as it returns an object per line, not a list
            }
            poi_data, message = get_property_data(url=LnP.pois_url, params=poi_params, session=session, location_is_poi=True)
            if not poi_data:
                return None, message

            poi_df = pd.DataFrame(poi_data)
            # First, check for exact match, then partial match if none found
            hits_df = poi_df[poi_df["name_primary"].str.lower() == location_name.lower()]
            if hits_df.empty:
                hits_df = poi_df[poi_df["name_primary"].str.contains(location_name, case=False, regex=False)]

            if not hits_df.empty:
                poi_id = float(hits_df.iloc[0]["id"])
                poi_latitude = float(hits_df.iloc[0]["lat"])
                poi_longitude = float(hits_df.iloc[0]["lon"])
#                 print("Found POI '{}'".format(hits_df.iloc[0]["name_primary"])) #/// Test print
                
                # Get list of TTICodes for a given place
                for parent_place in hits_df.iloc[0]["places"]:
                    # Perform authenticated request
                    parent_place_url = LnP.get_place_url(parent_place)
                    parent_place_params = {
                        "showcolumns": "tticodes",
                        "format": "json"
                    }

                    raw_place_data, message = get_property_data(url=parent_place_url, params=parent_place_params, session=session, location_is_poi=False)
                    if not raw_place_data:
                        print(f"Error fetching place {parent_place}: {message}")
                    else:
                        parent_place_data = raw_place_data[parent_place]
                        # Get TTICodes
                        for property_code in parent_place_data.get("tticodes", []):
                            property_codes.add(int(property_code))

        if len(property_codes) == 0:
            return None, "POI not found."
#         print("Property codes: {}\n\n".format(property_codes))
    
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
#     print("Property DataFrame length: {}\n".format(len(property_df.index)))

    # Get info for each property
    if "TTICODE" in property_df.columns:
        property_df = property_df[
            (property_df["Searchable Property Type"].astype(str).str.contains(searchable_type, case=False, na=False, regex=False)) &
            (property_df["TTICODE"].isin(property_codes)) &
            (property_df["DEFAULT_RATING"].fillna(0) >= min_rating)
        ]
#         print(property_df.head())
#         print("Filtered length: {}\n\n".format(len(property_df.index)))
    else:
        return None, "Property data import failed."
    


    ### STEP 3: Import facts for each property, and filter as required ###
    # --- Load the CSV with FACT IDs + keywords ---
    fact_df = pd.read_csv(LnP.property_facts_csv_path, header=[0,1])

    # Create a mapping of FACT ID to keywords
    fact_keywords = {}

    for _, row in fact_df.iterrows():
        if not math.isnan(row["FACT ID"].iloc[0]):
            fact_id = str(int(row["FACT ID"].iloc[0])).strip()   # Normalize FACT ID to string
            keywords = {
                col[1] for col in fact_df.columns[1:]   # Skip "FACT ID" col
                if str(row[col]).lower() == "x"
            }
            fact_keywords[fact_id] = keywords
    
    # --- Get the fact IDs from the XML ---
    # Cache facts locally and fetch missing GIATA IDs in parallel to speed up repeated runs
    facts_cache_path = os.path.join(cache_dir, "giata_facts.parquet")
    if os.path.exists(facts_cache_path):
        facts_cache_df = pd.read_parquet(facts_cache_path)
        # Ensure GIATA_ID dtype matches property_df values
        facts_cache = {int(r["GIATA_ID"]): set(r["KEYWORDS"].split("||")) if r["KEYWORDS"] else set() for _, r in facts_cache_df.iterrows()}
    else:
        facts_cache = {}

    giata_ids = [int(x) for x in property_df["GIATA ID"].tolist()]
    ids_to_fetch = [gid for gid in giata_ids if gid not in facts_cache]

    # Prepare session with retries
    session_f = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    session_f.mount("https://", HTTPAdapter(max_retries=retries))

    def fetch_giata_fact_ids(gid):
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
            futures = {exe.submit(fetch_giata_fact_ids, gid): gid for gid in ids_to_fetch}
            for fut in concurrent.futures.as_completed(futures):
                gid, keywords = fut.result()
                facts_cache[gid] = keywords

        # Persist cache as parquet for future runs (serialize sets as "||" joined string)
        cache_rows = [{"GIATA_ID": k, "KEYWORDS": "||".join(sorted(v))} for k, v in facts_cache.items()]
        pd.DataFrame(cache_rows).to_parquet(facts_cache_path, index=False)

    session_f.close()

    # Build the list of matching keyword sets in the same order as property_df
    all_matching_keywords = [facts_cache.get(int(gid), set()) for gid in property_df["GIATA ID"]]

    # Apply required_keywords filter
    mask = [required_keywords.issubset(keywords) for keywords in all_matching_keywords]

    # Convert sets to comma-separated, title-cased strings
    property_df["KEYWORDS"] = [
        ", ".join(sorted([kw.title() for kw in keywords])) if keywords else ""
        for keywords in all_matching_keywords
    ]
    
    # Filter out rows that don't match all required keywords
    if len(required_keywords) > 0:
        property_df = property_df[mask].reset_index(drop=True)
#         print("DF filtered by facts:\n{}\n\n".format(property_df))



    ### STEP 4: Sort by distance to POI if applicable, and filter if requested ###
    if location_is_poi or nearby_poi_type: # Calculate distance from POI (Haversine formula)
        def haversine(lat1, lon1, lat2, lon2):
            # Convert decimal degrees to radians
            lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
            # Haversine formula
            lat_diff = lat2 - lat1
            lon_diff = lon2 - lon1
            a = math.sin(lat_diff/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(lon_diff/2)**2
            c = 2 * math.asin(math.sqrt(a))
            r = 6371  # Radius of the Earth in kilometers. Use 3959 for miles
            return c * r

        # Get more accurate lat/long from provided spreadsheet
        if location_is_poi:
            if (
                poi_id in poi_info_df["POIS ID"].values and
                not math.isnan(poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lat"]) and
                not math.isnan(poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lon"])
            ):
#                 print("Using verified POI lat/long.")
#                 print("Old lat/long: {}, {}".format(poi_latitude, poi_longitude))
                poi_latitude = poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lat"]
                poi_longitude = poi_info_df[poi_info_df["POIS ID"] == poi_id].iloc[0]["Actual Lon"]
#                 print("New lat/long: {}, {}\n\n".format(poi_latitude, poi_longitude))
#             else:
#                 print("Using POI lat/long from API.\n\n")

            # Apply distance calculation
            property_df["DISTANCE (km)"] = property_df.apply(lambda row: haversine(poi_latitude, poi_longitude, row["LATITUDE"], row["LONGITUDE"]), axis=1)
            property_df.sort_values(by="DISTANCE (km)", inplace=True)

#             print(property_df.head())
#             print("Sorted by distance to POI.\n\n")
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

            for _, prop in property_df.iterrows():
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

            property_df["NEARBY POI LIST"] = poi_lists
            property_df["CLOSEST POI"] = closest_poi_names
            # Keep numeric distances for correct numeric sorting/filtering
            property_df["DISTANCE (km)"] = nearest_distances

            # Sort numerically by nearest distance, putting rows with no POIs last
            property_df.sort_values(by="DISTANCE (km)", inplace=True, na_position="last")

#             print(property_df.head())
#             print("Built full POI lists and sorted by nearest POI.\n\n")

        # Filter by minimum distance if specified
        if max_distance > 0:
            property_df = property_df[property_df["DISTANCE (km)"] <= max_distance]
#             print(property_df.head())
#             print("Filtered by maximum distance of {} km.\n\n".format(max_distance))
        
        # Format distance column for display, trimming each value to 2 decimal places
        property_df["DISTANCE (km)"] = property_df["DISTANCE (km)"].map(lambda v: f"{v:.2f}" if pd.notnull(v) else "")



    ### STEP 5: Filter down to 20 ###
    if len(property_df.index) > 20:
        property_df = property_df.head(20) #/// Should I be ordering the places in any particular way?


    
    ### STEP 6: Tidy up data before returning ###
    # Drop columns not needed in output, and rename RATING column
    property_df = property_df.drop(columns=["GIATA ID", "LATITUDE", "LONGITUDE", "ACCURACY", "CHAINS", "PRIMARY_PROPERTY_TYPE", "Unnamed: 12", "Include / Exclude Ind", "Searchable Property Type"],
                     errors='ignore')
    property_df = property_df.rename(columns={"DEFAULT_RATING": "RATING"})
    return property_df, ""



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