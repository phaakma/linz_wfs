import arcpy
import requests
import json
import sys
from pathlib import Path
from datetime import datetime
import time
import re
import logging
from json.decoder import JSONDecodeError

current_dir = Path.cwd()
config_directory = current_dir / "config"
data_directory = current_dir / "data"
logs_directory = current_dir / "logs"
wfs_url = None
logger = None
from_commandline = False
proxies = None

sample_settings = {
    "api_key": "xxxxxxxxxxxxxxxxxxxxx",
    "data_directory": "",
    "logs_directory": "",
    "config_directory": "",
    "proxies": {"http": "", "https": ""},
}

sample_config = {
    "wfs_request_params": {"typename": "layer-50318", "srsname": "EPSG:2193"},
    "id_field": "t50_fid",
    "config_name": "AllNZRailStationPoints",
}


def init(config_supplied=False):
    global wfs_url, logger, from_commandline, config_directory, data_directory, logs_directory, proxies

    # if running from commandline then the first argument will
    # be the file path.
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    arg_script_path = Path(str(sys.argv[0])).resolve()
    from_commandline = script_path == arg_script_path
    settings_file = script_dir / "settings.json"
    _settings = sample_settings
    if settings_file.exists():
        with open(settings_file, "r") as file:
            _settings = json.load(file)
    else:
        with settings_file.open("w") as file:
            json.dump(sample_settings, file, indent=4)

    # set up logging before anything else
    _logs_directory = _settings.get("logs", None)
    logs_directory = (
        Path(_logs_directory) if _logs_directory is not None else logs_directory
    )
    logger = configureLogging()
    logging_level = _settings.get("logging_level", logging.DEBUG)
    logger.setLevel(logging_level)

    _config_directory = _settings.get("config", None)
    _data_directory = _settings.get("data", None)

    config_directory = (
        Path(_config_directory) if _config_directory is not None else config_directory
    )
    data_directory = (
        Path(_data_directory) if _data_directory is not None else data_directory
    )
    ensure_folder(config_directory)
    ensure_folder(data_directory)

    # create a sample file if it doesn't exist
    _sample_config_file = config_directory / "sample.json"
    if not _sample_config_file.exists():
        with _sample_config_file.open("w") as file:
            json.dump(sample_config, file, indent=4)

    api_key = _settings.get("api_key", None)
    if api_key is None:
        logger.error(
            "No api key found! Please update the settings.json file with a valid LINZ api key. Aborting."
        )
        exit(1)
    wfs_url = f"https://data.linz.govt.nz/services;key={api_key}/wfs"

    # set proxies if any exist in the settings file
    _proxies = _settings.get("proxies", None)
    if _proxies.get("http") or _proxies.get("https"):
        proxies = _proxies

    logger.debug("...")
    logger.debug(
        f"Script initialised **********************************************************"
    )
    return


def ensure_folder(folder):
    """Create a folder if it doesn't exist"""
    if isinstance(folder, str):
        folder = Path(folder)
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        if logger:
            logger.debug(f"Folder '{folder}' created.")


class ArcpyHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        if record.levelno >= logging.ERROR:
            arcpy.AddError(log_entry)
        elif record.levelno >= logging.WARNING:
            arcpy.AddWarning(log_entry)
        else:
            arcpy.AddMessage(log_entry)

    def close(self):
        pass


def configureLogging():

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
    file_logging_handler = logging.FileHandler(logFileWithExtension)
    arcpy_handler = ArcpyHandler()

    consoleHandler.setLevel(logging.INFO)
    file_logging_handler.setLevel(logging.DEBUG)
    arcpy_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    )
    consoleHandler.setFormatter(formatter)
    file_logging_handler.setFormatter(formatter)
    arcpy_handler.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(file_logging_handler)
    if from_commandline:
        logger.addHandler(consoleHandler)
    else:
        logger.addHandler(arcpy_handler)

    return logger


def timing_decorator(func):
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


def is_valid_feature_class_name(name):
    pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
    return bool(re.match(pattern, name))


def replace_non_alphanumeric_with_underscore(input_string):
    # Use regex to replace non-alphanumeric characters with underscore
    return re.sub(r"[^a-zA-Z0-9_]", "_", input_string)


def load_latest_json_file(foldername):
    """
    Given a folder this finds the json
    file most recently created, loads and
    returns it.
    """
    # Ensure foldername is a Path object
    if isinstance(foldername, str):
        foldername = Path(foldername)

    # Find the latest file with the given extension based on creation date
    latest_file = None
    latest_time = None
    file_extension = "json"

    for file in foldername.glob(f"*{file_extension}"):
        creation_time = file.stat().st_ctime
        if latest_time is None or creation_time > latest_time:
            latest_time = creation_time
            latest_file = file

    # Load the latest file into a dictionary
    if latest_file:
        with open(latest_file, "r") as file:
            data_dict = json.load(file)
        logger.debug(f"Loaded data from {latest_file}:")
        return data_dict
    else:
        logger.debug(
            f"No files with extension '{file_extension}' found in the directory."
        )
        return None


def update_nested_dict(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and k in d:
            d[k] = update_nested_dict(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def loadLayerParameters(config_file):

    logger.debug(f"Loading configuration from: {config_file}")

    min_params = ["config_name", "id_field"]
    min_wfs_params = [
        "service",
        "version",
        "request",
        "outputFormat",
        "typename",
    ]
    with open(config_file, "r") as file:
        data = json.load(file)

    params = {
        "wfs_request_params": {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "srsname": "EPSG:2193",
            "outputFormat": "json",
        }
    }

    # Update the params dictionary with values from data
    params = update_nested_dict(params, data)
    logger.debug(f"Full configuration: {params}")

    missing_parameters = [p for p in min_params if p not in params]
    if missing_parameters:
        logger.error("Missing input parameters for this layer. Aborting.")
        logger.error(missing_parameters)
        exit(1)
    missing_wfs_parameters = [
        p for p in min_wfs_params if p not in params["wfs_request_params"]
    ]
    if missing_wfs_parameters:
        logger.error("Missing input wfs parameters for this layer. Aborting.")
        logger.error(missing_wfs_parameters)
        exit(1)

    return params


@timing_decorator
def downloadWFSData(url, params, output_file):

    logger.debug("Downloading WFS data to JSON file.")
    logger.debug(wfs_url)
    logger.debug(params)
    # Make the request and stream the response to a file
    response = requests.get(url, params=params, stream=True, proxies=proxies)
    with open(output_file, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"WFS data download complete and saved to: {output_file}.")

    try:
        # Get the timeStamp to return
        with open(output_file, "r") as file:
            data = json.load(file)
        del data["features"]
        logger.debug(f"Timestamp of downloaded data: {data.get('timeStamp', None)}")
    except JSONDecodeError as jErr:
        logger.error(
            f"Error encountered parsing the downloaded data. Check the download file for error messages."
        )
        logger.error(jErr)
        exit(1)
    return data


@timing_decorator
def convertJsonToFGB(layer_data_directory, json_file, layer, id_field):
    """
    The json_file should be geojson FeatureCollection.
    This function creates a staging file geodatabase in the
    layer data directory if necessary.
    Then deletes any existing feature class with this layer name.
    Then converts the json to feature class using the standard JSONToFeatures
    GP tool.
    Unfortunately, LINZ id fields are integers which the GP tool interprets
    as doubles. This makes data manipulation later harder. To cater for this,
    the script copies the data to a temp field, deletes the original double id field,
    recreates the id field as integer and copies the data back.
    """

    logger.debug("Converting JSON data to feature class.")
    uniqueIdentifier_fieldname = "_uniqueIdentifier"

    fgb_name = "staging.gdb"
    fgb = layer_data_directory / fgb_name
    fc_name = slugify(layer)
    fc = fgb / fc_name

    if not is_valid_feature_class_name(fc_name):
        logger.info("Layername is not a valid feature class name. Aborting.")
        exit(1)

    # create a file geodatabase if it doesn't exist.
    if not arcpy.Exists(str(fgb)):
        logger.debug("Staging file geodatabase didn't exist, creating it now.")
        arcpy.management.CreateFileGDB(str(layer_data_directory), fgb_name)
    else:
        # Compact the file geodatabase to give best performance for upcoming edits.
        arcpy.management.Compact(str(fgb))

    # convert json file into feature class.
    # The environment variables force no Z or M values
    # which can slow down later processing.
    with arcpy.EnvManager(
        outputZFlag="Disabled",
        outputMFlag="Disabled",
        overwriteOutput=True
    ):
        arcpy.conversion.JSONToFeatures(
            in_json_file=str(json_file), out_features=str(fc)
        )

    # The GP tool interprets the integer identifier field as a double. This makes
    # later analysis difficult. Here we add our own integer id field and populate it.
    # This assumes that LINZ id fields are always integers.
    arcpy.management.AddField(
        in_table=str(fc),
        field_name=uniqueIdentifier_fieldname,
        field_type="LONG",
        field_precision=None,
        field_scale=None,
        field_length=None,
        field_alias="",
        field_is_nullable="NULLABLE",
        field_is_required="NON_REQUIRED",
        field_domain="",
    )
    arcpy.management.CalculateField(
        in_table=str(fc),
        field=uniqueIdentifier_fieldname,
        expression=f"!{id_field}!",
        expression_type="PYTHON3",
        code_block="",
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS",
    )
    arcpy.management.DeleteField(
        in_table=str(fc), drop_field=id_field, method="DELETE_FIELDS"
    )
    arcpy.management.AddField(
        in_table=str(fc),
        field_name=id_field,
        field_type="LONG",
        field_precision=None,
        field_scale=None,
        field_length=None,
        field_alias="",
        field_is_nullable="NULLABLE",
        field_is_required="NON_REQUIRED",
        field_domain="",
    )
    arcpy.management.AddIndex(
        in_table=str(fc),
        fields=id_field,
        index_name="id_idx2",
        unique="UNIQUE",
        ascending="NON_ASCENDING",
    )
    arcpy.management.CalculateField(
        in_table=str(fc),
        field=id_field,
        expression=f"!{uniqueIdentifier_fieldname}!",
        expression_type="PYTHON3",
        code_block="",
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS",
    )
    arcpy.management.DeleteField(
        in_table=str(fc), drop_field=uniqueIdentifier_fieldname, method="DELETE_FIELDS"
    )

    logger.info(f"Finished converting JSON data to feature class.")
    return fc


@timing_decorator
def applyChangeset(changeset, target_dataset, id_field):
    global editSession

    changeset = str(changeset)
    target_dataset = str(target_dataset)

    count_changeset = arcpy.management.GetCount(changeset)
    count_target = arcpy.management.GetCount(target_dataset)

    logger.info(f"Applying {count_changeset} changes from: {changeset}")
    logger.info(f"Applying changeset to: {target_dataset}")
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
    count_inserts = result.getOutput(1)
    logger.debug(f"Number of INSERT from the changeset: {count_inserts}")
    result = arcpy.management.SelectLayerByAttribute(
        changeset_layername,
        selection_type="NEW_SELECTION",
        where_clause="__change__ = 'UPDATE'",
    )
    count_updates = result.getOutput(1)
    logger.debug(f"Number of UPDATE from the changeset: {count_updates}")
    result = arcpy.management.SelectLayerByAttribute(
        changeset_layername,
        selection_type="NEW_SELECTION",
        where_clause="__change__ = 'DELETE'",
    )
    count_deletes = result.getOutput(1)
    logger.debug(f"Number of DELETE from the changeset: {count_deletes}")
    arcpy.Delete_management(changeset_layer)

    fields = [id_field]
    where_clause = "LOWER(__change__) = 'delete'"
    delete_ids = [
        str(row[0])
        for row in arcpy.da.SearchCursor(changeset, fields, where_clause=where_clause)
    ]

    logger.debug(
        f"Number of records to delete calculated from list of ids: {len(delete_ids)}"
    )
    delete_ids_string = ",".join(delete_ids)

    where_clause = f"{id_field} in ({delete_ids_string})"
    target_layername = "target_layer"
    target_layer = arcpy.management.MakeFeatureLayer(
        target_dataset, target_layername, where_clause=where_clause
    )

    arcpy.management.DeleteRows(target_layer)
    arcpy.Delete_management(target_layer)

    logger.debug("Inserting and updating records...")
    arcpy.management.Append(
        inputs=changeset,
        target=target_dataset,
        schema_type="NO_TEST",
        field_mapping=None,
        subtype="",
        expression="__change__ IN ('INSERT', 'UPDATE')",
        match_fields=f"{id_field} {id_field}",
        update_geometry="UPDATE_GEOMETRY",
    )

    logger.info(
        f"Number of rows in target after changes applied: {arcpy.management.GetCount(target_dataset)}"
    )


@timing_decorator
def updateTarget(source_feature_class, target_dataset, is_changeset, id_field):
    logger.debug(f"Updating specified target: {target_dataset}")
    if not arcpy.Exists(target_dataset):
        logger.error(f"Target dataset does not exist. Skipping update.")
        return

    if is_changeset:
        logger.debug(f"Applying changeset.")
        applyChangeset(
            changeset=source_feature_class,
            target_dataset=target_dataset,
            id_field=id_field,
        )
    else:
        logger.info(f"About to truncate the target and append all new features.")
        ## WARNING!
        # Truncate does not work if target is versioned or has attachments.
        # Must use Delete Rows GP tool instead. This can be quite slow, especially
        # for large tables.

        target_describe = arcpy.da.Describe(target_dataset)
        is_versioned = target_describe.get("isVersioned", False)
        has_attachments = any(
            "ATTACHREL" in str(r).upper()
            for r in target_describe.get("relationshipClassNames", [])
        )
        if is_versioned or has_attachments:
            logger.info(
                f"Target is either versioned ({is_versioned}) or has attachments ({has_attachments}). Using DeleteRows which may be slow to complete."
            )
            arcpy.management.DeleteRows(target_dataset)
        else:
            logger.debug(f"Target is not versioned. Using TruncateTable GP tool.")
            arcpy.management.TruncateTable(target_dataset)

        logger.info(f"About to append data.")
        logger.info(source_feature_class)
        logger.info(target_dataset)

        arcpy.management.Append(
            inputs=str(source_feature_class),
            target=str(target_dataset),
            schema_type="NO_TEST",
            field_mapping=None,
        )
        logger.info(f"Finished updating target dataset.")


@timing_decorator
def main(*args, **kwargs):

    # Ensure we have a configuration file
    config_filename = arcpy.GetParameterAsText(0)
    config_filename = (
        config_filename
        if config_filename is not None and config_filename.strip() != ""
        else None
    )
    init(config_filename)

    if config_filename is None:
        logger.error("Missing input argument for config file. Aborting.")
        exit(1)

    # Load Layer parameters
    config_file = config_directory / config_filename
    logger.info(f"Layer config file: {config_file}")
    params = loadLayerParameters(config_file)

    # Make data directory for this dataset
    config_name = slugify(params["config_name"])
    layername = params["wfs_request_params"]["typename"]
    is_changeset = layername.endswith("-changeset")
    if is_changeset:
        # Remove the suffix "-changeset"
        layername = layername[: -len("-changeset")]
    layername = slugify(layername)

    layer_data_directory = data_directory / layername / config_name
    ensure_folder(layer_data_directory)
    logger.info(f"Layer data directory is: {layer_data_directory}")

    last_updated_file = layer_data_directory / "_last_updated.json"
    if is_changeset:
        if not last_updated_file.exists():
            logger.error(
                f"Processing a changeset requires knowing a date to retrieve changes from. This is fetched from the '_last_updated.json' file in the data directory. Creating a new _last_updated.json file now, please update the datetime in it if necessary."
            )
            with open(last_updated_file, "w") as file:
                json.dump({"last_updated": f"{datetime.utcnow().isoformat()}Z"}, file)
            exit(1)
        else:
            with open(last_updated_file, "r") as file:
                last_updated_data = json.load(file)
                changes_from = last_updated_data.get("last_updated", None)
        changes_to = f"{datetime.utcnow().isoformat()}Z"
        logger.debug(f"Changes date range (UTC): from:{changes_from};to:{changes_to}")
        params["wfs_request_params"][
            "viewparams"
        ] = f"from:{changes_from};to:{changes_to}"

    # Download WFS data to Json File
    layername_full = slugify(params["wfs_request_params"]["typename"])
    now_utc = datetime.utcnow()
    datetime_suffix = now_utc.strftime("%Y%m%d_%H%M%S")
    output_file = layer_data_directory / f"{layername_full}_{datetime_suffix}.json"
    download_details = downloadWFSData(
        wfs_url, params["wfs_request_params"], output_file
    )

    if int(download_details.get("numberReturned", 0)) == 0:
        logger.warning(
            "There were no features in the download. Skipping applying any updates."
        )
    else:
        # Convert the JSON WFS FeatureCollection to a Feature Class
        feature_class = convertJsonToFGB(
            layer_data_directory,
            json_file=output_file,
            layer=layername_full,
            id_field=params["id_field"],
        )

        # Apply the changes from the changeset to the staging data
        # Disabled this flow for now. Using the auto generated 
        # feature class from the json to features GP tool was causing
        # issues. 

        # if is_changeset:
        #     staging_fc = str(feature_class)[: -len("-changeset")]
        #     if arcpy.Exists(staging_fc):
        #         applyChangeset(
        #             changeset=feature_class,
        #             target_dataset=staging_fc,
        #             id_field=params["id_field"],
        #         )
        #     else:
        #         logger.warning(
        #             f"Staging fc does not exist to apply changeset to. Skipping this step."
        #         )

        # Apply new data to target_feature_class
        target_feature_class = params.get("target_feature_class", None)
        if target_feature_class:
            updateTarget(
                source_feature_class=feature_class,
                target_dataset=target_feature_class,
                is_changeset=is_changeset,
                id_field=params["id_field"],
            )
        else:
            logger.info(f"No target specified. Downloaded data is available in the staging.gdb")

    # Update the "_last_updated.json" file
    download_timestamp = download_details.get("timeStamp", None)
    if download_timestamp:
        with open(last_updated_file, "w") as file:
            json.dump({"last_updated": download_timestamp}, file)

    logger.info(f"Finished")
    return


if __name__ == "__main__":
    main()
