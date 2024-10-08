############################################################
#  LINZ_WFS.py
#
#  Command line driven utility script for exporting
#  LINZ layers and applying changesets.
#
#  Author: Paul Haakma
#  Contact: paul_haakma@eagle.co.nz
#  Created: June 2024
#
############################################################

import arcpy
import requests
import json
from pathlib import Path
from datetime import datetime
import time
import re
import logging
from json.decoder import JSONDecodeError
import argparse
import zipfile
import tempfile
import os

arcpy.env.overwriteOutput = True

current_dir = Path.cwd()
data_directory = current_dir / "data"
logs_directory = current_dir / "logs"
wfs_url = f"https://data.linz.govt.nz/services/wfs"

logger = None
proxies = None
settings = None
headers = None
config_name = None
layer_id = None
id_field = None
wkid = None
extent = None
changeset = False
full_download = False
layer_data_directory = None
config_file = None
last_updated_file = None
last_updated_datetime = None
params = None
extent_featureclass = None
extent_geometry = None
sql_filter = None
initial_buffer = 1000
staging_fgb_name = "staging.gdb"
target_feature_class = None
retain_after_purge = None
poll_interval = 10  # seconds
max_polling_time = 600  # seconds


def init(config_name, is_first_setup=False):
    """
    Initialise the script, read settings and configuration
    from file.
    If required: create directories, create staging file
    geodatabase and empty extent feature class.
    """
    global logger, config_file, settings, last_updated_file
    global data_directory, layer_data_directory
    global extent_featureclass, logs_directory, proxies, headers

    # load in the settings file or create it.
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    settings_file = script_dir / "settings.json"
    settings = {
        "api_key": "",
        "data_directory": "",
        "logs_directory": "",
        "proxies": {"http": "", "https": ""},
    }
    if settings_file.exists():
        with open(settings_file, "r") as file:
            settings = json.load(file)
    else:
        with settings_file.open("w") as file:
            json.dump(settings, file, indent=4)

    # set up logging before anything else
    # _logs_directory = settings.get("logs", None)
    _data_directory = settings.get("data_directory", None)
    data_directory = (
        Path(_data_directory)
        if _data_directory is not None and _data_directory.strip() != ""
        else data_directory
    )
    layer_data_directory = data_directory / config_name
    ensure_folder(layer_data_directory)
    logs_directory = layer_data_directory / "logs"
    logger = configureLogging()
    logging_level = settings.get("logging_level", logging.DEBUG)
    logger.setLevel(logging_level)

    logger.info(f"Initializing. Loading settings.")

    api_key = settings.get("api_key", None)
    if not is_first_setup and (api_key is None or api_key.strip() == ""):
        logger.error(
            "No api key found! Please update the settings.json file with a valid LINZ api key. Aborting."
        )
        exit(1)
    headers = {"Authorization": f"key {api_key}"}

    # create a sample file if it doesn't exist
    config_file = layer_data_directory / "config.json"
    last_updated_file = layer_data_directory / "last_updated.json"

    if not config_file.exists():
        logger.warning(f"This is the initial setup for this configuration.")
        if not layer_id:
            logger.error(f"Please specify the layer id using the --layer option.")
        if not id_field:
            logger.error("Please specify the LINZ id field using the --idfield option.")
        if not layer_id or not id_field:
            exit(1)
    if not config_file.exists():
        is_first_setup = True
        _wkid = wkid if wkid is not None else "2193"
        _config = {
            "layer_id": layer_id,
            "wkid": _wkid,
            "id_field": id_field,
            "sql_filter": None,
            "target_feature_class": None,
            "retain_after_purge": 5,
            "initial_buffer": 1000,
            "poll_interval": 10,
            "max_polling_time": 600,
        }
        with config_file.open("w") as file:
            json.dump(_config, file, indent=4)
        if not last_updated_file.exists():
            update_last_updated_file()

    # set proxies if any exist in the settings file
    _proxies = settings.get("proxies", None)
    if _proxies.get("http") or _proxies.get("https"):
        proxies = _proxies

    fgb = layer_data_directory / staging_fgb_name
    # create a file geodatabase if it doesn't exist.
    if not arcpy.Exists(str(fgb)):
        logger.debug("Staging file geodatabase didn't exist, creating it now.")
        arcpy.management.CreateFileGDB(str(layer_data_directory), staging_fgb_name)
    else:
        # Compact the file geodatabase to give best performance for upcoming edits.
        arcpy.management.Compact(str(fgb))

    extent_featureclass = str(fgb / "extent")
    if not arcpy.Exists(extent_featureclass):
        arcpy.management.CreateFeatureclass(
            out_path=str(fgb),
            out_name="extent",
            geometry_type="POLYGON",
            has_m="DISABLED",
            has_z="DISABLED",
            spatial_reference='PROJCS["NZGD_2000_New_Zealand_Transverse_Mercator",GEOGCS["GCS_NZGD_2000",DATUM["D_NZGD_2000",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",1600000.0],PARAMETER["False_Northing",10000000.0],PARAMETER["Central_Meridian",173.0],PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0]];-2147483647 -2147483647 20000;-100000 10000;-100000 10000;0.0001;0.001;0.001;IsHighPrecision',
        )

    logger.debug(f"..............Script initialised..................")
    return is_first_setup


def ensure_folder(folder):
    """Create a folder if it doesn't exist"""
    if isinstance(folder, str):
        folder = Path(folder)
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        if logger:
            logger.debug(f"Folder '{folder}' created.")


def configureLogging():
    """
    Set up a logger to a logfile and standard out.
    If the log file is larger than 10MB then it
    rolls over to a new log file.
    """

    ensure_folder(logs_directory)
    # If the log file exists and is larger than 10MB
    # then rename it as a backup.
    logFileName = "logfile"
    logFileWithExtension = logs_directory / f"{logFileName}.log"
    if (
        logFileWithExtension.exists()
        and logFileWithExtension.stat().st_size / 1048576 > 10
    ):
        utcnow = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        new_file_path = logFileWithExtension.with_name(
            f"{logFileWithExtension.stem}_{utcnow}_{logFileWithExtension.suffix}"
        )
        logFileWithExtension.rename(new_file_path)

    current_file = Path(__file__).name
    logger = logging.getLogger(current_file)
    logger.handlers = []
    logger.setLevel(logging.DEBUG)

    consoleHandler = logging.StreamHandler()
    file_logging_handler = logging.FileHandler(logFileWithExtension, encoding='utf-8')

    consoleHandler.setLevel(logging.INFO)
    file_logging_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    )
    consoleHandler.setFormatter(formatter)
    file_logging_handler.setFormatter(formatter)

    logger.addHandler(file_logging_handler)
    logger.addHandler(consoleHandler)
    return logger


def timing_decorator(func):
    """
    A helper wrapper function to time other functions.
    """

    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time
        logger.debug(
            f"Function '{func.__name__}' took {elapsed_time:.4f} seconds to complete."
        )
        return result

    return wrapper


def slugify(text, to_lower=False):
    """
    Convert a string to a safe string that can
    be used as a folder or file name.
    """
    text = text.strip()
    # Define a translation table to replace invalid characters with an underscore
    invalid_chars = '-<>:"/\\|?*'
    translation_table = str.maketrans(invalid_chars, "_" * len(invalid_chars))
    # Translate the text to replace invalid characters
    text = text.translate(translation_table)
    # Replace spaces with underscores
    text = text.replace(" ", "_")
    # Remove any remaining characters that are not alphanumeric, underscore, or hyphen
    text = re.sub(r"[^a-zA-Z0-9_-]", "", text)
    # Add an underscore in front if the first character is a digit
    # This ensures it can also be used as a feature class name.
    if text and text[0].isdigit():
        text = "_" + text
    # Optionally, convert to lowercase
    if to_lower:
        text = text.lower()
    return text


def update_nested_dict(d, u):
    """
    Given two dictionaries, update the first one
    (d) with all entries from the second one (u).
    Does this recursively.
    """
    for k, v in u.items():
        if isinstance(v, dict) and k in d:
            d[k] = update_nested_dict(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def update_last_updated_file(update_time=None):
    """
    Updates the last_updated.json file for the
    current configuration being processed.
    update_time is an ISO date string in UTC.
    """
    if isinstance(update_time, datetime):
        update_time = f"{update_time.isoformat()}Z"
    elif update_time == None:
        update_time = f"{datetime.utcnow().isoformat()}Z"

    with open(last_updated_file, "w") as file:
        json.dump({"last_updated": update_time}, file)
    logger.info(f"The last updated file has been set to: {update_time}")
    return


def loadConfiguration():
    """
    Load configuration from file.
    """
    logger.info(f"Loading configuration from: {config_file}")
    global params, layer_id, poll_interval, max_polling_time, sql_filter
    global retain_after_purge, id_field, target_feature_class, initial_buffer

    with open(config_file, "r") as file:
        data = json.load(file)

    wkid = data.get("wkid", "2193")
    layer_id = data.get("layer_id", None)
    if layer_id is None:
        logger.error(
            "Missing layer_id in config.json file. Please fix and re-run. Aborting."
        )
        exit()
    id_field = data.get("id_field", None)
    if id_field is None:
        logger.error(
            f"Missing id_field in config.json file. Please fix and re-run. Aborting."
        )
        exit()
    poll_interval = data.get("poll_interval", poll_interval)
    max_polling_time = data.get("max_polling_time", max_polling_time)
    target_feature_class = data.get("target_feature_class", None)
    retain_after_purge = data.get("retain_after_purge", retain_after_purge)
    initial_buffer = data.get("initial_buffer", initial_buffer)
    bbox_string = None
    sql_filter = data.get("sql_filter", None)
    cql_filter = data.get("cql_filter", None)
    if cql_filter is None:
        ## cql_filter and bbox cannot be used together.
        getExtentGeometry()
        if extent_geometry is not None:
            bbox_string = geometryToBboxString(extent_geometry)

    params = {
        "service": "WFS",
        "version": "2.0.0",
        "typename": f"layer-{layer_id}-changeset",
        "request": "GetFeature",
        "srsname": f"EPSG:{wkid}",
        "outputFormat": "json",
        "cql_filter": cql_filter,
        "bbox": bbox_string,
    }

    return params


def getExtentGeometry():
    """
    Fetch the first record from the extent_featureclass
    in the staging file geodatabase.
    """
    global extent_geometry
    if extent_geometry is not None:
        return extent_geometry

    extent_records = [
        row[0] for row in arcpy.da.SearchCursor(extent_featureclass, ["SHAPE@"])
    ]
    if len(extent_records) == 0:
        extent_geometry = None
    else:
        extent_geometry = extent_records[0]
    return extent_geometry


def geometryToGeojson(in_geometry):
    """
    https://github.com/jasonbot/geojson-madness/blob/master/geojson_out.py#L22-58
    """

    def part_split_at_nones(part_items):
        current_part = []
        for item in part_items:
            if item is None:
                if current_part:
                    yield current_part
                current_part = []
            else:
                current_part.append((item.X, item.Y))
        if current_part:
            yield current_part

    in_geometry = in_geometry.projectAs(arcpy.SpatialReference(4326))

    if in_geometry is None:
        return None
    elif isinstance(in_geometry, arcpy.PointGeometry):
        pt = in_geometry.getPart(0)
        return {"type": "Point", "coordinates": (pt.X, pt.Y)}
    elif isinstance(in_geometry, arcpy.Polyline):
        parts = [
            [(point.X, point.Y) for point in in_geometry.getPart(part)]
            for part in range(in_geometry.partCount)
        ]
        if len(parts) == 1:
            return {"type": "LineString", "coordinates": parts[0]}
        else:
            return {"type": "MultiLineString", "coordinates": parts}
    elif isinstance(in_geometry, arcpy.Polygon):
        parts = [
            list(part_split_at_nones(in_geometry.getPart(part)))
            for part in range(in_geometry.partCount)
        ]
        if len(parts) == 1:
            return {"type": "Polygon", "coordinates": parts[0]}
        else:
            return {"type": "MultiPolygon", "coordinates": parts}
    else:
        raise ValueError(in_geometry)


def geometryToBboxString(in_geometry):
    """
    Convert a geometry to a BBOX string.
    XMin,YMin,XMax,YMax,EPSG:wkid
    """
    in_geometry = in_geometry.projectAs(arcpy.SpatialReference(4326))
    extent = in_geometry.extent
    bbox_string = f"{extent.XMin},{extent.YMin},{extent.XMax},{extent.YMax},EPSG:{extent.spatialReference.factoryCode}"
    return bbox_string


def initiate_export(_layer_id):
    """
    Request a data export from LINZ, intiate the export and
    return the export id.
    """
    logger.info("Downloading a full dataset as file geodatabase.")
    requests_url = "https://data.linz.govt.nz/services/api/v1.x/exports/"
    validation_url = f"{requests_url}validate/"

    data = {
        "crs": params["srsname"],
        "items": [
            {"item": f"https://data.linz.govt.nz/services/api/v1.x/layers/{_layer_id}/"}
        ],
        "formats": {"vector": "applicaton/x-ogc-filegdb"},
    }

    getExtentGeometry()
    if extent_geometry is not None:
        # The export API crops features, so we buffer now and clean up later.
        buffered_extent = extent_geometry.buffer(initial_buffer).extent.polygon
        geojson_extent = geometryToGeojson(buffered_extent)
        data["extent"] = geojson_extent
    logger.debug(data)

    # Send a validate request to LINZ to check for errors
    response = requests.post(validation_url, headers=headers, json=data)
    if response.status_code in (200, 201, "200", "201"):
        try:
            json_response = response.json()
            if any(not item.get("is_valid", "true") for item in json_response["items"]):
                logger.error(
                    "LINZ returned an error when attempting to validate an export with this configuration. Check for 'invalid_reasons' in the logs."
                )
                logger.error(json_response[items])
                exit()
        except ValueError as e:
            logger.debug(f"Error parsing JSON from export validation: {e}")
            exit()
    else:
        logger.debug(
            f"Failed export validation with status code: {response.status_code}"
        )
        logger.debug(response)
        exit()

    logger.debug("Export parameters passed LINZ validation check.")

    # Make the actual request to LINZ for the fgb to be generated.
    last_updated_datetime = datetime.utcnow()
    response = requests.post(requests_url, headers=headers, json=data)
    if response.status_code in (200, 201, "200", "201"):
        try:
            json_response = response.json()
        except ValueError as e:
            logger.debug(f"Error parsing JSON from export request: {e}")
            exit()
    else:
        logger.debug(f"Failed export request with status code: {response.status_code}")
        exit()

    export_id = json_response.get("id")
    status_url = json_response.get("url")
    logger.info(f"Export id is: {export_id}")
    return export_id


def download_export(export_id):
    """
    Polls LINZ for a given export id and downloads
    it when finished.
    """
    logger.info(
        f"Downloading {export_id}. Polling every {poll_interval} seconds for a maximum of {max_polling_time} seconds"
    )

    start_time = time.time()
    status_url = f"https://data.linz.govt.nz/services/api/v1.x/exports/{export_id}/"
    download_url = f"{status_url}download/"

    attempt = 0

    while (time.time() - start_time) < max_polling_time:
        attempt += 1
        poll_response = requests.get(status_url, headers=headers)

        if poll_response.status_code not in (200, 201, "200", "201"):
            logger.error(
                f"Polling failed with status code: {poll_response.status_code}"
            )
            logger.error(f"Polling Response Content: {poll_response.text}")
            break
        try:
            poll_json_response = poll_response.json()
            state = poll_json_response.get("state")
            progress = round(float(poll_json_response.get("progress")), 2)

            if state == "complete":
                logger.debug(f"Polling successful. State: {state}")
                break
            else:
                logger.debug(
                    f"Polling attempt: {attempt}, Progress: {progress}, State: {state}"
                )
        except ValueError as e:
            logger.error(f"Error parsing polling JSON: {e}")
            break

        time.sleep(poll_interval)
    else:
        logger.error(
            "Polling finished: reached the limit of attempts or time. If necessary, consider increasing these limits in the configuration file."
        )
        logger.error(
            f"You can resume polling for this export by using --resume {export_id}."
        )
        exit()

    datetime_suffix = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    download_dir = layer_data_directory / "full"
    ensure_folder(download_dir)
    download_file = download_dir / f"layer_{layer_id}_{datetime_suffix}.zip"
    response = requests.get(download_url, headers=headers, stream=True)
    if response.status_code in (200, 201, "200", "201"):
        # Open a local file in write-binary mode
        with open(download_file, "wb") as file:
            # Iterate over the response content in chunks
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
    else:
        logger.error(f"Failed to download file. Status code: {response.status_code}")
        logger.error(f"Response Content: {response.text}")
        exit()

    logger.info(f"Export downloaded to zip file: {download_file}")
    return download_file


def copy_fc_to_staging(zip_path):
    """
    zip_path will be a Path object pointing to the
    downloaded zip file containing the file geodatabase.
    Extract to temp location, copy the feature class
    within it to the staging.gdb and then delete
    the temp data.
    """
    logger.info(f"Copying feature class to staging file geodatabase")
    # Create a temporary directory in the same directory as the zip file
    if isinstance(zip_path, str):
        zip_path = Path(zip_path)
    with tempfile.TemporaryDirectory(dir=zip_path.parent) as temp_dir:
        temp_path = Path(temp_dir)

        # Extract the zip file to the temporary directory
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_path)

        # get list of file geodatabases in the temp folder. get the first one.
        arcpy.env.workspace = temp_dir
        gdb = arcpy.ListWorkspaces("*", "FileGDB")[0]
        logger.debug(gdb)
        arcpy.env.workspace = gdb
        in_features = arcpy.ListFeatureClasses()[0]
        logger.debug(in_features)
        out_features = layer_data_directory / staging_fgb_name / f"layer_{layer_id}"

        arcpy.conversion.ExportFeatures(
            in_features=in_features, out_features=str(out_features)
        )
        arcpy.management.Delete(gdb)
        convertIdFieldToInteger(out_features)
    return out_features


def deleteFeaturesNotIntersectingExtent(feature_class):
    """
    Delete all features in the given feature class that
    don't intersect the extent.
    """
    getExtentGeometry()
    if extent_geometry is None:
        return

    logger.info(f"Deleting all feature that don't intersect the extent")
    lyr = arcpy.management.MakeFeatureLayer(
        in_features=str(feature_class), out_layer="temp_layer"
    )
    arcpy.management.SelectLayerByLocation(
        lyr,
        overlap_type="INTERSECT",
        select_features=extent_featureclass,
        invert_spatial_relationship="INVERT",
    )
    arcpy.management.DeleteRows(lyr)
    arcpy.Delete_management(lyr)
    return


def deleteFeaturesNotMatchingSQL(feature_class):
    """
    Delete all features in the given feature class that
    don't match the given SQL where_clause.
    """
    if sql_filter is None:
        return
    logger.info(f"Deleting all features that don't match the given SQL expression")
    lyr = arcpy.management.MakeFeatureLayer(
        in_features=str(feature_class), out_layer="temp_layer"
    )
    arcpy.management.SelectLayerByAttribute(
        in_layer_or_view=lyr, where_clause=sql_filter, invert_where_clause="INVERT"
    )
    arcpy.management.DeleteRows(lyr)
    arcpy.Delete_management(lyr)
    return


@timing_decorator
def downloadChangeSet():
    """
    Download a changeset from LINZ for this layer.
    """
    global last_updated_datetime
    logger.info("Downloading WFS changeset data to JSON file.")
    if last_updated_file is None or not last_updated_file.exists():
        logger.error(
            f"Processing a changeset requires knowing a date to retrieve changes from. Please run a full download or manually resolve this before attempting a changeset."
        )
        exit(1)
    else:
        with open(last_updated_file, "r") as file:
            last_updated_data = json.load(file)

    changes_from = last_updated_data.get("last_updated", None)
    if not changes_from:
        logger.error(f"Error getting last updated time from file. Aborting.")
        exit(1)

    now_utc = datetime.utcnow()
    changes_to = f"{now_utc.isoformat()}Z"
    logger.debug(f"Changes date range (UTC): from:{changes_from};to:{changes_to}")

    params["viewparams"] = f"from:{changes_from};to:{changes_to}"

    datetime_suffix = now_utc.strftime("%Y%m%dT%H%M%S")

    download_dir = layer_data_directory / "changesets"
    ensure_folder(download_dir)

    output_file = download_dir / f"layer_{str(layer_id)}_{datetime_suffix}.json"

    logger.debug(params)
    # Make the request and stream the response to a file
    response = requests.get(
        wfs_url,
        headers=headers,
        params=params,
        stream=True,
        proxies=proxies,
    )
    with open(output_file, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"WFS data download complete and saved to: {output_file}.")

    try:
        # Get the timeStamp to return
        with open(output_file, "r", encoding="utf-8") as file:
            data = json.load(file)
        last_updated_datetime = data.get("timeStamp", None)
        if int(data.get("numberReturned", 0)) == 0:
            logger.info(
                "There were no features in the download. Skipping applying any updates."
            )
            return None
        del data
        logger.debug(f"Timestamp of downloaded data: {last_updated_datetime}")
    except JSONDecodeError as jErr:
        logger.error(
            f"Error encountered parsing the downloaded data. Check the download file for error messages."
        )
        logger.error(jErr)
        exit(1)
    return output_file


@timing_decorator
def convertJsonToFGB(json_file):
    """
    The json_file should be geojson FeatureCollection.
    Converts the json to feature class using the standard JSONToFeatures
    GP tool.
    Unfortunately, LINZ id fields are integers which the GP tool interprets
    as doubles. This makes data manipulation later harder. To cater for this,
    the script copies the data to a temp field, deletes the original double id field,
    recreates the id field as integer and copies the data back.
    """

    logger.info("Converting JSON data to feature class.")
    datetime_suffix = str(Path(json_file).stem).split("_")[-1]
    logger.debug(f"datetime_suffix is: {datetime_suffix}")
    fc = (
        layer_data_directory
        / staging_fgb_name
        / f"layer_{layer_id}_changeset_{datetime_suffix}"
    )
    with arcpy.EnvManager(
        outputZFlag="Disabled", outputMFlag="Disabled", overwriteOutput=True
    ):
        arcpy.conversion.JSONToFeatures(
            in_json_file=str(json_file), out_features=str(fc)
        )

    convertIdFieldToInteger(fc)

    return fc


def convertIdFieldToInteger(fc):
    """
    LINZ primary key fields are listed on their website as integer,
    but in the exported file geodatabase are sometimes double.
    Also, the conversion from geojson to feature class interprets the number
    as a float too.
    This function converts a field to an integer data type.
    Without doing this, the upsert process doesn't correctly match
    identifiers.
    """
    logger.info(f"Converting {id_field} to integer type in {fc}")
    fc = str(fc)
    fields = [f for f in arcpy.ListFields(fc) if f.name == id_field]
    if len(fields) == 0:
        logger.warning(f"Could not find {id_field} in {fc}")
        return
    field = fields[0]
    if field.type not in ("Double", "Float", "Integer", "SmallInteger"):
        logger.warning(
            f"{id_field} not a number field in {fc}, cannot convert to integer"
        )
        return
    if field.type == "Integer":
        logger.info(
            f"{id_field} is already an integer data type, no need to convert the data type"
        )
        arcpy.management.AddIndex(
            in_table=fc,
            fields=id_field,
            index_name="id_idx2",
            unique="UNIQUE",
            ascending="NON_ASCENDING",
        )
        return

    temp_fieldname = "_uniqueIdentifier"
    arcpy.management.AddField(
        in_table=fc,
        field_name=temp_fieldname,
        field_type="LONG",
        field_is_nullable="NULLABLE",
        field_is_required="NON_REQUIRED",
    )
    arcpy.management.CalculateField(
        in_table=fc,
        field=temp_fieldname,
        expression=f"!{id_field}!",
        expression_type="PYTHON3",
        code_block="",
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS",
    )
    arcpy.management.DeleteField(
        in_table=fc, drop_field=id_field, method="DELETE_FIELDS"
    )
    arcpy.management.AddField(
        in_table=fc,
        field_name=id_field,
        field_type="LONG",
        field_is_nullable="NULLABLE",
        field_is_required="NON_REQUIRED",
    )
    arcpy.management.AddIndex(
        in_table=fc,
        fields=id_field,
        index_name="id_idx2",
        unique="UNIQUE",
        ascending="NON_ASCENDING",
    )
    arcpy.management.CalculateField(
        in_table=fc,
        field=id_field,
        expression=f"!{temp_fieldname}!",
        expression_type="PYTHON3",
        code_block="",
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS",
    )
    arcpy.management.DeleteField(
        in_table=fc, drop_field=temp_fieldname, method="DELETE_FIELDS"
    )

    logger.info(f"Finished converting id field to integer.")
    return fc


@timing_decorator
def applyChangeset(changeset, target_fc):
    """
    Both changeset and target_fc will be
    feature classes.
    Outputs feature counts to aid troubleshooting.
    Uses the Append GP tool with upserts to apply changes.
    """
    global editSession

    changeset = str(changeset)
    target_fc = str(target_fc)

    count_changeset = int(arcpy.management.GetCount(changeset).getOutput(0))
    count_target = int(arcpy.management.GetCount(target_fc).getOutput(0))

    logger.info(f"Applying {count_changeset} changes from: {changeset}")
    logger.info(f"Applying changeset to: {target_fc}")
    logger.info(f"Number of rows in target before applying changes: {count_target}")

    changeset_layername = "changeset_layer"
    changeset_layer = arcpy.management.MakeFeatureLayer(changeset, changeset_layername)

    # Get counts of inserts, updates and deletes. This has no functional purpose but
    # is helpful for troubleshooting.

    result = arcpy.management.SelectLayerByAttribute(
        changeset_layername,
        selection_type="NEW_SELECTION",
        where_clause="__change__ = 'INSERT'",
    )
    count_inserts = int(result.getOutput(1))
    logger.info(f"Number of INSERT from the changeset: {count_inserts}")
    result = arcpy.management.SelectLayerByAttribute(
        changeset_layername,
        selection_type="NEW_SELECTION",
        where_clause="__change__ = 'UPDATE'",
    )
    count_updates = int(result.getOutput(1))
    logger.info(f"Number of UPDATE from the changeset: {count_updates}")
    result = arcpy.management.SelectLayerByAttribute(
        changeset_layername,
        selection_type="NEW_SELECTION",
        where_clause="__change__ = 'DELETE'",
    )
    count_deletes = int(result.getOutput(1))
    logger.info(f"Number of DELETE from the changeset: {count_deletes}")
    arcpy.Delete_management(changeset_layer)

    fields = [id_field]
    where_clause = "LOWER(__change__) = 'delete'"
    delete_ids = [
        str(row[0])
        for row in arcpy.da.SearchCursor(changeset, fields, where_clause=where_clause)
    ]

    if int(count_deletes) > 0:
        logger.debug("Deleting records.")
        delete_ids_string = ",".join(delete_ids)
        where_clause = f"{id_field} in ({delete_ids_string})"
        target_layername = "target_layer"
        target_layer = arcpy.management.MakeFeatureLayer(
            target_fc, target_layername, where_clause=where_clause
        )

        arcpy.management.DeleteRows(target_layer)
        arcpy.Delete_management(target_layer)

## NOTE: using the Append GP tool and match fields to do an upsert
## didn't seem to reliably work. So changed to using an append plus
## a custom applyUpdates function
    if count_inserts > 0:
        logger.debug("Inserting new records...")
        arcpy.management.Append(
            inputs=changeset,
            target=target_fc,
            schema_type="NO_TEST",
            field_mapping=None,
            subtype="",
            expression="__change__ = 'INSERT'",
            update_geometry="UPDATE_GEOMETRY",
        )

    if count_updates > 0:
        logger.debug("Applying updates to existing records...")
        processUpdates(changeset, target_fc, id_field)

    final_total = int(arcpy.management.GetCount(target_fc).getOutput(0))
    logger.info(f"Number of rows in target after changes applied: {final_total}")

    expected_total = count_target - count_deletes + count_inserts
    if expected_total != final_total:
        diff = expected_total - final_total
        logger.warning(
            f"Expected total of {expected_total} does not match actual final total {final_total}. Out by {diff}"
        )

@timing_decorator
def processUpdates(source, target, id_field):
    """ 
    Applies updates from the source to the target.
    The source is a changeset with a __change__ field.
    The target is expected to have the same schema.
    """ 
    logger.info(f"In the processUpdates function!")

    source_desc = arcpy.da.Describe(source)
    target_desc = arcpy.da.Describe(target)

    source_fields = [field.name.lower() for field in source_desc.get("fields")]
    target_fields = [field.name.lower() for field in target_desc.get("fields")]

    logger.debug(f"Source fields: {source_fields}")
    logger.debug(f"Target fields: {target_fields}")

    # Exclude the GlobalID and OID fields
    exclude_fields = [source_desc.get("globalIDFieldName"), source_desc.get("OIDFieldName"),
                      target_desc.get("globalIDFieldName"), target_desc.get("OIDFieldName")]

    source_fields = [f for f in source_fields if f not in exclude_fields]
    target_fields = [f for f in target_fields if f not in exclude_fields]

    # Identify date and text fields
    date_fields = [f.name.lower() for f in target_desc.get("fields") if f.type == 'Date']
    text_fields = [f.name.lower() for f in target_desc.get("fields") if f.type == 'String']

    # Store rows to be updated in a dictionary keyed by the record id
    updates_dict = {}
    with arcpy.da.SearchCursor(in_table=source, field_names=source_fields, where_clause="__change__ = 'UPDATE'") as cursor:
        for row in cursor:
            record_id = row[source_fields.index(id_field)]
            updates_dict[record_id] = row
    del cursor 

    # Use a single UpdateCursor to apply updates in bulk
    with arcpy.da.UpdateCursor(in_table=target, field_names=target_fields) as updateCursor:
        for r in updateCursor:
            record_id = r[target_fields.index(id_field)]
            if record_id in updates_dict:
                row = updates_dict[record_id]
                for field in target_fields:
                    val = row[source_fields.index(field)]
                    if field in date_fields:
                        dt = datetime.strptime(val, '%Y-%m-%dT%H:%M:%SZ')
                        r[target_fields.index(field)] = dt
                    else:
                        r[target_fields.index(field)] = val
                updateCursor.updateRow(r)
    del updateCursor

    return


@timing_decorator
def updateTarget(source_feature_class, target_fc, is_changeset):
    """
    Both source_feature_class and target_fc
    """
    logger.info(f"Updating specified target: {target_fc}")
    if not arcpy.Exists(target_fc):
        logger.error(f"Target dataset does not exist. Skipping update.")
        return

    if is_changeset:
        logger.debug(f"Applying changeset.")
        applyChangeset(changeset=source_feature_class, target_fc=target_fc)
    else:
        logger.info(f"About to truncate the target and append all new features.")
        ## WARNING!
        # arcpy.management.TruncateTable does not work if target is versioned or has attachments.
        # Must use Delete Rows GP tool instead. This can be quite slow, especially
        # for large tables. Not a recommended combination.

        target_describe = arcpy.da.Describe(target_fc)
        is_versioned = target_describe.get("isVersioned", False)
        has_attachments = any(
            "ATTACHREL" in str(r).upper()
            for r in target_describe.get("relationshipClassNames", [])
        )
        if is_versioned or has_attachments:
            logger.info(
                f"Target is either versioned ({is_versioned}) or has attachments ({has_attachments}). Using DeleteRows which may be slow to complete."
            )
            arcpy.management.DeleteRows(target_fc)
        else:
            logger.debug(f"Target is not versioned. Using TruncateTable GP tool.")
            arcpy.management.TruncateTable(target_fc)

        logger.info(f"About to append data.")
        logger.info(source_feature_class)
        logger.info(target_fc)

        arcpy.management.Append(
            inputs=str(source_feature_class),
            target=str(target_fc),
            schema_type="NO_TEST",
            field_mapping=None,
        )
        logger.info(f"Finished updating target dataset.")


def purgeChangesets():
    """
    Delete old changesets, retain the last number
    as specified by retain_after_purge configuration setting.
    """
    if not retain_after_purge:
        logger.info("No retain_after_purge number specified, skipping purge.")
        return

    # Delete changeset json files
    logger.info("Purging old changeset json files")
    changesets_directory = layer_data_directory / "changesets"
    json_files = list(changesets_directory.glob("*.json"))
    json_files.sort(key=lambda x: os.path.getctime(x), reverse=True)
    files_to_delete = json_files[retain_after_purge:]
    for file in files_to_delete:
        try:
            file.unlink()  # Delete the file
            logger.debug(f"Deleted: {file}")
        except Exception as e:
            logger.warning(f"Error deleting {file}: {e}")

    # Delete full download zip files
    logger.info("Purging old full download zip files")
    full_directory = layer_data_directory / "full"
    zip_files = list(full_directory.glob("*.zip"))
    zip_files.sort(key=lambda x: os.path.getctime(x), reverse=True)
    files_to_delete = zip_files[retain_after_purge:]
    for file in files_to_delete:
        try:
            file.unlink()  # Delete the file
            logger.debug(f"Deleted: {file}")
        except Exception as e:
            logger.warning(f"Error deleting {file}: {e}")

    # Delete changeset feature classes
    staging_fgb = layer_data_directory / staging_fgb_name
    arcpy.env.workspace = str(staging_fgb)
    feature_classes = arcpy.ListFeatureClasses()

    # Filter feature classes that contain "changeset" in their names
    logger.info("Purging old changeset feature classes")
    changeset_feature_classes = [fc for fc in feature_classes if "changeset" in fc]
    changeset_feature_classes.sort()
    feature_classes_to_delete = changeset_feature_classes[:-retain_after_purge]
    for fc in feature_classes_to_delete:
        try:
            arcpy.Delete_management(fc)
            logger.debug(f"Deleted: {fc}")
        except Exception as e:
            logger.warning(f"Error deleting {fc}: {e}")
    return


def checkArguments(args):
    """
    Certain combinations of arguments are expected and some
    combinations would not be valid as they conflict.
    """
    # Mus do one and only one of init, full, changeset, resume, json or zip.
    variables = [args.init, args.changeset, args.download, args.resume, args.json, args.zip]
    not_none_count = sum(bool(var) for var in variables)
    if not_none_count == 0:
        print(
            f"Please specify either --init, --download, --changeset, --resume or --zip."
        )
        print(variables)
        exit()
    elif not_none_count > 1:
        print(
            f"Please specify only one of --init, --download, --changeset, --resume or --zip."
        )
        print(variables)
        exit(1)

    return True


@timing_decorator
def main(args):
    """
    Takes the given arguments and calls the necessary functions
    to process the request.
    """
    global config_name, layer_id, id_field, wkid, changeset, full_download

    config_name = slugify(args.name)
    layer_id = args.layer
    initialise = args.init
    id_field = args.field
    wkid = args.wkid
    changeset = args.changeset
    full_download = args.download
    export_id = args.resume
    zip_file_to_process = args.zip
    purge_changesets = args.purge
    json_file = args.json
    if json_file is not None:
        changeset = True 

    checkArguments(args)

    # initialize
    is_first_setup = init(config_name=config_name, is_first_setup=initialise)
    if is_first_setup:
        logger.info(
            f"Layer data directory created with new config.json file. Please review config file and update if necessary before proceeding."
        )
        exit()
    if initialise:
        logger.info(f"Layer data directory initialised. {layer_data_directory}")
        exit()

    logger.info(f"Name is: {config_name}")
    loadConfiguration()

    if layer_id is None:
        # by this point we should always have a layer id.
        logger.error(f"Missing layer id. Please run using the --init option first.")
        exit(1)

    if full_download:
        export_id = initiate_export(layer_id)
    if export_id is not None:
        zip_file_to_process = download_export(export_id=export_id)
    if zip_file_to_process is not None:
        source_feature_class = copy_fc_to_staging(zip_path=zip_file_to_process)
        deleteFeaturesNotIntersectingExtent(str(source_feature_class))
        deleteFeaturesNotMatchingSQL(str(source_feature_class))
    source_feature_class = None
    if changeset:
        if json_file is None:
            json_file = downloadChangeSet()
        if json_file is not None:
            logger.info(json_file)
            source_feature_class = convertJsonToFGB(json_file=str(json_file))
            deleteFeaturesNotIntersectingExtent(str(source_feature_class))
            deleteFeaturesNotMatchingSQL(str(source_feature_class))

            # Apply the changes from the changeset to the staging data
            full_feature_class = (
                layer_data_directory / staging_fgb_name / f"layer_{layer_id}"
            )
            applyChangeset(
                changeset=str(source_feature_class),
                target_fc=str(full_feature_class),
            )

    if (
        (full_download or changeset)
        and source_feature_class is not None
        and target_feature_class is not None
    ):
        # Apply new data to target_feature_class
        updateTarget(
            source_feature_class=source_feature_class,
            target_feature_class=target_feature_class,
            is_changeset=changeset,
        )

    update_last_updated_file(last_updated_datetime)

    if purge_changesets:
        purgeChangesets()

    logger.info(f"Finished")
    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="LINZ WFS",
        description="Python script to download LINZ datasets to ArcGIS feature class and keep updated using changesets.",
    )
    parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="A user specified friendly name for this download. Use file and folder friendly text, avoid special characters and spaces.",
    )
    parser.add_argument(
        "-i",
        "--init",
        action="store_true",
        help="Flag to initialise a data folder, create config file and staging.gdb but don't download anything.",
    )
    parser.add_argument(
        "-l", "--layer", help="Required on initial setup, this is the LINZ layer id."
    )
    parser.add_argument(
        "-f",
        "--field",
        help="Required on initial setup, this is the name of the LINZ id field for this layer.",
    )
    parser.add_argument(
        "-c",
        "--changeset",
        action="store_true",
        help="Flag indicating to download the layer changeset.",
    )
    parser.add_argument(
        "-p",
        "--purge",
        action="store_true",
        help="Flag indicating whether to purge old changesets.",
    )
    parser.add_argument(
        "-d",
        "--download",
        action="store_true",
        help="Flag indicating to download the full layer dataset.",
    )

    parser.add_argument(
        "-w",
        "--wkid",
        help="Required on initial setup, this is the desired wkid to use. If not specified it defaults to 2193 (NZTM)",
    )

    parser.add_argument(
        "-r", "--resume", help="Resume polling for a previous full export attempt."
    )

    parser.add_argument(
        "-z",
        "--zip",
        help="Process an already downloaded zip file. Provide the full path to the zip file with this option.",
    )

    parser.add_argument(
        "-j",
        "--json",
        help="Process an already downloaded changes json file. Provide the full path to the json file with this option.",
    )

    args = parser.parse_args()
    main(args)
