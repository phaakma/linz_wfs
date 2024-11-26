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
from enum import Enum
from typing import Union
from datetime import datetime
import time
import re
import logging
from logging.handlers import RotatingFileHandler
from json.decoder import JSONDecodeError
import argparse
import zipfile
import tempfile
import os
import configparser
import shutil

config = configparser.ConfigParser()
arcpy.env.overwriteOutput = True
current_dir = Path.cwd()
script_path = Path(__file__).resolve()
script_dir = script_path.parent
logs_directory = script_dir / "logs"
logs_directory.mkdir(parents=True, exist_ok=True)
logger = None

def configureLogging(log_dir):
    """
    Set up a logger to a logfile and standard out.
    If the log file is larger than 10MB then it
    rolls over to a new log file.
    """

    log_dir = Path(log_dir)
    logFileName = "logfile"
    log_file_with_extension = log_dir / f"{logFileName}.log"
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        logger.handlers.clear()

    consoleHandler = logging.StreamHandler()

    file_logging_handler = RotatingFileHandler(
        log_file_with_extension,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,  # Keep up to 5 backups
        encoding='utf-8',
    )
    consoleHandler.setLevel(logging.INFO)
    file_logging_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(lineno)s - %(message)s"
    )
    consoleHandler.setFormatter(formatter)
    file_logging_handler.setFormatter(formatter)

    logger.addHandler(file_logging_handler)
    logger.addHandler(consoleHandler)
    return logger

def init(args):
    """
    Initialise the script, read settings and configuration
    from file.
    Create a LinzDataset object from the provided options.
    """

    ### This section is global, not for the LINZDataset object.
    settings_file = script_dir / "settings.cnf"
    settings_template = script_dir / "template.cnf"

    if not settings_file.is_file():
        logger.warning('First run, cloning config template. Please update configuration file.')
        shutil.copy(settings_template, settings_file)
        return False
    else:
        config.read(settings_file)
    #########################################################

    if not args.name:
        raise TypeError(f"No --name argument was provided.")
    if args.name not in config:
        raise ValueError(f'No config section found for {args.name}. Please update configuration file.')

    settings = config[args.name]

    _action = ActionToTake.INIT
    _export_id = None
    _file_to_process = None 
    if args.init:
        _action = ActionToTake.INIT
    elif args.download:
        _action = ActionToTake.REQUESTDOWNLOAD
    elif args.resume:
        _action = ActionToTake.DOWNLOADEXPORT
        _export_id = args.resume
    elif args.localfull:
        _action = ActionToTake.PROCESSFULLDOWNLOAD
        _file_to_process = args.localfull
    elif args.changeset:
        _action = ActionToTake.REQUESTCHANGESET
    elif args.localchangeset:
        _action = ActionToTake.PROCESSJSONCHANGESET
        _file_to_process = args.localchangeset

    linz_dataset = LINZDataset( 
        config_name=args.name,
        settings=settings,
        action=_action,
        export_id=_export_id,
        file_to_process=_file_to_process,
        purge = args.purge
        )

    logger.debug(f"..............Script initialised..................")
    return linz_dataset

class ActionToTake(Enum):
    INIT = 100
    REQUESTDOWNLOAD = 200
    DOWNLOADEXPORT = 210
    PROCESSFULLDOWNLOAD = 220    
    REQUESTCHANGESET = 300
    PROCESSJSONCHANGESET = 310   

class LINZError(Exception):
    """Custom exception for configuration-related issues."""
    pass


class LINZDataset:
    """
    A LINZ dataset that can download data and changesets.

    Attributes:
        data_dir (str): Location of the data directory.
        class_var (type): Description of class variable.
    """
    
    # Class variable 
    logger = logging.getLogger(__name__)
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    wfs_url = "https://data.linz.govt.nz/services/wfs"
    requests_url = "https://data.linz.govt.nz/services/api/v1.x/exports/"
    validation_url = f"{requests_url}validate/"
    layer_download_url = "https://data.linz.govt.nz/services/api/v1.x/layers/"
    last_updated_datetime = None
    extent_geometry = None
    extent = None
    staging_fgb_name = "staging.gdb"
    full_download_file = None
    layer_feature_class = None
    changeset_file = None 
    changeset_fc = None 
    purge = False
    proxies = None 
    
    def __init__(
        self,        
        config_name: str,
        settings,
        action: ActionToTake,
        export_id: Union[str, None] = None,
        file_to_process: str = None,
        purge: bool = False
        ):
        """
        The constructor for MyClass.

        Args:
            instance_var (str): The value to initialize the instance variable.
        """
        
        self._config_name = config_name
        self.settings = settings
        self.action = action
        self.export_id = export_id
        self.purge = purge 

        if self.action == ActionToTake.PROCESSFULLDOWNLOAD:
            self.full_download_file = Path(file_to_process)
        elif self.action == ActionToTake.PROCESSJSONCHANGESET:
            self.changeset_file = Path(file_to_process)

        self.logger.info(f"purge: {str(self.purge)}")

        _api_key = self.settings.get("api_key", "")
        self.headers = {"Authorization": f"key {_api_key}"}

        self.layer_id = self.settings.get("layer_id")
        self.id_field = self.settings.get("id_field")
        self.wkid = self.settings.getint("wkid", 2193)
        self.sql_filter = self.settings.get("sql_filter")

        _data_directory = self.settings.get("data_directory")
        self.data_directory = (
            Path(_data_directory)
            if _data_directory is not None and _data_directory.strip() != ""
            else self.script_dir / "data"
            )   
        self.layer_data_directory = self.data_directory / self.slugify(self.config_name)
        self.changeset_directory = self.layer_data_directory / "changesets"
        self.fulldownload_directory = self.layer_data_directory / "full"
        self.last_updated_file = self.layer_data_directory / "last_updated.json"
        self.staging_fgb = self.layer_data_directory / self.staging_fgb_name
        self.layer_feature_class = self.layer_data_directory / self.staging_fgb_name / f"layer_{self.layer_id}"
        self.extent_featureclass = self.staging_fgb / "extent"
        
        self.poll_interval = self.settings.getint("poll_interval", 10)  #seconds
        self.max_polling_time = self.settings.getint("max_polling_time", 600) #seconds
        self.retain_after_purge = self.settings.getint("retain_after_purge", 5)
        self.initial_buffer = self.settings.getint("initial_buffer", 1000)  #meters
        _proxies = self.settings.get("proxies", None)
        if self.settings.get("http_proxy") or self.settings.get("https_proxy"):
            self.proxies = {
                "http": self.settings.get("http_proxy", ""),
                "https": self.settings.get("https_proxy", "")
            }
            self.logger.info(self.proxies)

        self.logger.info(f"LINZDataset initialized.")

    def __str__(self):
        """
        String representation of the object.

        Returns:
            str: A human-readable string describing the object.
        """
        return f"""    Config section: {self.config_name}
    Layer Directory: {self.layer_data_directory}
    Action: {self.action}"""

    def __repr__(self):
        """
        Official string representation of the object, typically for debugging.

        Returns:
            str: A string describing the object for developers.
        """
        return f"""    Config section: {self.config_name}
    Layer Directory: {self.layer_data_directory}
    Action: {self.action}"""

    @property 
    def config_name(self):
        """The config_name property."""
        return self._config_name.lower()

    @property 
    def wfs_params(self) -> dict:
        """Return dictionary of WFS parameters"""
        bbox_string = None        
        cql_filter = self.settings.get("cql_filter", None)
        if cql_filter is None:
            ## cql_filter and bbox cannot be used together.
            self.getExtentGeometry()
            if self.extent_geometry is not None:
                bbox_string = self.geometryToBboxString(self.extent_geometry)
        return {
                "service": "WFS",
                "version": "2.0.0",
                "typename": f"layer-{self.layer_id}-changeset",
                "request": "GetFeature",
                "srsname": f"EPSG:{self.wkid}",
                "outputFormat": "json",
                "cql_filter": cql_filter,
                "bbox": bbox_string,
            }

    @property
    def number_of_changes(self) -> int:
        """
        Returns the number of changes in the current changeset file.
        """
        if not self.changeset_file.is_file():
            return 0
        with open(self.changeset_file, "r", encoding="utf-8") as file:
            data = json.load(file)
        return int(data.get("numberReturned", 0))

    def timing_decorator(func):
        """
        A helper wrapper function to time other functions.
        """
        def wrapper(*args, **kwargs):
            self = args[0]
            start_time = time.time()
            result = func(*args, **kwargs)
            end_time = time.time()
            elapsed_time = end_time - start_time
            self.logger.debug(
                f"Function '{func.__name__}' took {elapsed_time:.4f} seconds to complete."
            )
            return result
        return wrapper

    @timing_decorator
    def test(self, stuff):
        self.logger.info("testing")

    def requestDownload(self):
        """
        If a full download is requested then this function calls
        the necessary functions.
        """
        self.prepare()
        self.initiate_export()
        self.downloadExport()

    def downloadExport(self):
        """
        Download an export file from LINZ and proceed to
        process it.
        """
        self.download_export()
        self.processFullDownload()

    def processFullDownload(self):
        """
        Process a zip file from a full download of data.
        """
        self.copy_fc_to_staging(zip_path=self.full_download_file)
        self.deleteFeaturesNotIntersectingExtent(self.layer_feature_class)
        self.deleteFeaturesNotMatchingSQL(self.layer_feature_class)
        self.update_last_updated_file()
        if self.purge:
            self.purgeChangesets()

    def requestChangeset(self):
        self.downloadChangeSet()
        self.processChangeSet()

    def processChangeSet(self):
        if self.number_of_changes > 0: 
            self.convertJsonToFGB()
            self.deleteFeaturesNotIntersectingExtent(self.changeset_fc)
            self.deleteFeaturesNotMatchingSQL(self.changeset_fc)
            self.applyChangeset()
            self.update_last_updated_file()
        else:
            self.logger.warning("There were no changes in the changeset file to process.")
        if self.purge:
            self.purgeChangesets()

    def prepare(self):
        """
        Prepare the dataset by creating a data folder and a
        staging file geodatabase.
        """         
        self.layer_data_directory.mkdir(parents=True, exist_ok=True)      
        
        # create a file geodatabase if it doesn't exist.
        if not arcpy.Exists(str(self.staging_fgb)):
            self.logger.debug("Staging file geodatabase didn't exist, creating it now.")
            arcpy.management.CreateFileGDB(str(self.layer_data_directory), self.staging_fgb_name)
        else:
            # Compact the file geodatabase to give best performance for upcoming edits.
            arcpy.management.Compact(str(self.staging_fgb))

        if not arcpy.Exists(str(self.extent_featureclass)):
            arcpy.management.CreateFeatureclass(
                out_path=str(self.staging_fgb),
                out_name="extent",
                geometry_type="POLYGON",
                has_m="DISABLED",
                has_z="DISABLED",
                spatial_reference='PROJCS["NZGD_2000_New_Zealand_Transverse_Mercator",GEOGCS["GCS_NZGD_2000",DATUM["D_NZGD_2000",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",1600000.0],PARAMETER["False_Northing",10000000.0],PARAMETER["Central_Meridian",173.0],PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0]];-2147483647 -2147483647 20000;-100000 10000;-100000 10000;0.0001;0.001;0.001;IsHighPrecision',
            )
        return

    @timing_decorator
    def initiate_export(self):
        """
        Request a data export from LINZ, intiate the export and
        return the export id.
        """
        self.logger.info("Downloading a full dataset as file geodatabase.")
        self.prepare()
        params = self.wfs_params
        data = {
            "crs": params["srsname"],
            "items": [
                {"item": f"{self.layer_download_url}{self.layer_id}/"}
            ],
            "formats": {"vector": "applicaton/x-ogc-filegdb"},
        }

        self.getExtentGeometry()
        if self.extent_geometry is not None:
            # The export API crops features, so we buffer now and clean up later.
            buffered_extent = self.extent_geometry.buffer(self.initial_buffer).extent.polygon
            geojson_extent = self.geometryToGeojson(buffered_extent)
            data["extent"] = geojson_extent
        self.logger.debug(data)

        # Send a validate request to LINZ to check for errors
        response = requests.post(self.validation_url, headers=self.headers, json=data)
        if response.status_code in (200, 201, "200", "201"):
            try:
                json_response = response.json()
                if any(not item.get("is_valid", "true") for item in json_response["items"]):
                    err = "LINZ returned an error when attempting to validate an export with this configuration. Check for 'invalid_reasons' in the logs."
                    self.logger.error( err )
                    self.logger.error(json_response[items])
                    raise LINZError(err)
            except ValueError as e:
                err = f"Error parsing JSON from export validation: {e}"
                self.logger.debug(err)
                raise LINZError(err)
        else:
            err =f"Failed export validation with status code: {response.status_code}"
            self.logger.debug(err)
            self.logger.debug(response)
            raise LINZError(err)

        self.logger.debug("Export parameters passed LINZ validation check.")

        # Make the actual request to LINZ for the fgb to be generated.
        self.last_updated_datetime = datetime.utcnow()
        response = requests.post(self.requests_url, headers=self.headers, json=data)
        if response.status_code in (200, 201, "200", "201"):
            try:
                json_response = response.json()
            except ValueError as e:
                err = f"Error parsing JSON from export request: {e}"
                self.logger.debug(err)
                raise LINZError(err)
        else:
            err = f"Failed export request with status code: {response.status_code}"
            self.logger.debug(err)
            raise LINZError(err)

        self.export_id = json_response.get("id")
        self.status_url = json_response.get("url")
        self.logger.info(f"Export id is: {self.export_id}")
        
        return self.export_id

    def download_export(self):
        """
        Polls LINZ for a export id and downloads
        it when finished.
        """
        self.logger.info(
            f"Downloading {self.export_id}. Polling every {self.poll_interval} seconds for a maximum of {self.max_polling_time} seconds"
        )

        start_time = time.time()
        status_url = f"https://data.linz.govt.nz/services/api/v1.x/exports/{self.export_id}/"
        download_url = f"{status_url}download/"

        attempt = 0

        while (time.time() - start_time) < self.max_polling_time:
            attempt += 1
            poll_response = requests.get(status_url, headers=self.headers)

            if poll_response.status_code not in (200, 201, "200", "201"):
                self.logger.error(
                    f"Polling failed with status code: {poll_response.status_code}"
                )
                self.logger.error(f"Polling Response Content: {poll_response.text}")
                break
            try:
                poll_json_response = poll_response.json()
                state = poll_json_response.get("state")
                progress = round(float(poll_json_response.get("progress")), 2)

                if state == "complete":
                    self.logger.debug(f"Polling successful. State: {state}")
                    break
                else:
                    self.logger.debug(
                        f"Polling attempt: {attempt}, Progress: {progress}, State: {state}"
                    )
            except ValueError as e:
                self.logger.error(f"Error parsing polling JSON: {e}")
                break

            time.sleep(self.poll_interval)
        else:
            err = "Polling finished: reached the limit of attempts or time. If necessary, consider increasing these limits in the configuration file. You can resume polling for this export by using --resume {self.export_id}."
            logger.error(err)
            raise LINZError(err)

        datetime_suffix = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        download_dir = self.layer_data_directory / "full"
        self.ensure_folder(download_dir)
        self.full_download_file = download_dir / f"layer_{self.layer_id}_{datetime_suffix}.zip"
        response = requests.get(download_url, headers=self.headers, stream=True)
        if response.status_code in (200, 201, "200", "201"):
            # Open a local file in write-binary mode
            with open(self.full_download_file, "wb") as file:
                # Iterate over the response content in chunks
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
        else:
            err = f"Failed to download file. Status code: {response.status_code}. Response Content: {response.text}"
            self.logger.error(err)       
            raise LINZError(err)

        self.logger.info(f"Export downloaded to zip file: {self.full_download_file}")        
        return self.full_download_file

    def copy_fc_to_staging(self, zip_path):
        """
        zip_path will be a Path object pointing to the
        downloaded zip file containing the file geodatabase.
        Extract to temp location, copy the feature class
        within it to the staging.gdb and then delete
        the temp data.
        """
        self.logger.info(f"Copying feature class to staging file geodatabase")
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
            self.logger.debug(gdb)
            arcpy.env.workspace = gdb
            in_features = arcpy.ListFeatureClasses()[0]
            self.logger.debug(in_features)            

            arcpy.conversion.ExportFeatures(
                in_features=in_features, out_features=str(self.layer_feature_class)
            )
            arcpy.management.Delete(gdb)
            self.convertIdFieldToInteger(self.layer_feature_class)
        return self.layer_feature_class


    @timing_decorator
    def downloadChangeSet(self):
        """
        Download a changeset from LINZ for this layer.
        """
        self.logger.info("Downloading WFS changeset data to JSON file.")
        if self.last_updated_file is None or not self.last_updated_file.is_file():
            raise LINZError(f"Processing a changeset requires knowing a date to retrieve changes from. Please run a full download or manually resolve this before attempting a changeset.")
        else:
            with open(self.last_updated_file, "r") as file:
                last_updated_data = json.load(file)

        changes_from = last_updated_data.get("last_updated", None)
        if not changes_from:
            raise LINZError(f"Error getting last updated time from file. Cannot generate changeset, please reset using a full download.")            

        now_utc = datetime.utcnow()
        changes_to = f"{now_utc.isoformat()}Z"
        self.logger.debug(f"Changes date range (UTC): from:{changes_from};to:{changes_to}")

        params = self.wfs_params
        params["viewparams"] = f"from:{changes_from};to:{changes_to}"
        datetime_suffix = now_utc.strftime("%Y%m%dT%H%M%S")
        self.changeset_directory.mkdir(parents=True, exist_ok=True)
        self.changeset_file = self.changeset_directory / f"layer_{str(self.layer_id)}_{datetime_suffix}.json"

        self.logger.debug(params)
        # Make the request and stream the response to a file
        response = requests.get(
            self.wfs_url,
            headers=self.headers,
            params=params,
            stream=True,
            proxies=self.proxies,
        )
        with open(self.changeset_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        self.logger.info(f"WFS data download complete and saved to: {self.changeset_file}.")

        try:
            # Get the timeStamp to return
            with open(self.changeset_file, "r", encoding="utf-8") as file:
                data = json.load(file)
            self.last_updated_datetime = data.get("timeStamp", None)
            #self.number_of_changes = int(data.get("numberReturned", 0))
            # if int(data.get("numberReturned", 0)) == 0:
            #     self.logger.info(
            #         "There were no features in the download. Skipping applying any updates."
            #     )
            #     return None
            del data
            self.logger.debug(f"Timestamp of downloaded data: {self.last_updated_datetime}")
        except JSONDecodeError as jErr:
            raise LINZError(
                f"Error encountered parsing the downloaded data. Check the download file for error messages."
            )
        return self.changeset_file


    @timing_decorator
    def convertJsonToFGB(self):
        """
        The self.changeset_file should be geojson FeatureCollection.
        Converts the json to feature class using the standard JSONToFeatures
        GP tool.
        Unfortunately, LINZ id fields are integers which the GP tool interprets
        as doubles. This makes data manipulation later on harder to perform. To cater for this,
        the script copies the data to a temp field, deletes the original double id field,
        recreates the id field as integer and copies the data back.
        """

        self.logger.info(f"Converting JSON data to feature class: {self.changeset_file}")
        datetime_suffix = str(Path(self.changeset_file).stem).split("_")[-1]
        self.logger.debug(f"datetime_suffix is: {datetime_suffix}")
        self.changeset_fc = (
            self.layer_data_directory
            / self.staging_fgb_name
            / f"layer_{self.layer_id}_changeset_{datetime_suffix}"
        )
        with arcpy.EnvManager(
            outputZFlag="Disabled", outputMFlag="Disabled", overwriteOutput=True
        ):
            arcpy.conversion.JSONToFeatures(
                in_json_file=str(self.changeset_file), out_features=str(self.changeset_fc)
            )

        self.convertIdFieldToInteger(self.changeset_fc)

        return self.changeset_fc


    @timing_decorator
    def applyChangeset(self):
        """
        Both changeset and target_fc will be
        feature classes.
        Outputs feature counts to aid troubleshooting.
        Uses the Append GP tool with upserts to apply changes.
        """
        #global editSession

        changeset = str(self.changeset_fc)
        target_fc = str(self.layer_feature_class)

        count_changeset = int(arcpy.management.GetCount(changeset).getOutput(0))
        count_target = int(arcpy.management.GetCount(target_fc).getOutput(0))

        self.logger.info(f"Applying {count_changeset} changes from: {changeset}")
        self.logger.info(f"Applying changeset to: {target_fc}")
        self.logger.info(f"Number of rows in target before applying changes: {count_target}")

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
        self.logger.info(f"Number of INSERT from the changeset: {count_inserts}")
        result = arcpy.management.SelectLayerByAttribute(
            changeset_layername,
            selection_type="NEW_SELECTION",
            where_clause="__change__ = 'UPDATE'",
        )
        count_updates = int(result.getOutput(1))
        self.logger.info(f"Number of UPDATE from the changeset: {count_updates}")
        result = arcpy.management.SelectLayerByAttribute(
            changeset_layername,
            selection_type="NEW_SELECTION",
            where_clause="__change__ = 'DELETE'",
        )
        count_deletes = int(result.getOutput(1))
        self.logger.info(f"Number of DELETE from the changeset: {count_deletes}")
        arcpy.Delete_management(changeset_layer)

        fields = [self.id_field]
        where_clause = "LOWER(__change__) = 'delete'"
        delete_ids = [
            str(row[0])
            for row in arcpy.da.SearchCursor(changeset, fields, where_clause=where_clause)
        ]

        if int(count_deletes) > 0:
            self.logger.debug("Deleting records.")
            delete_ids_string = ",".join(delete_ids)
            where_clause = f"{self.id_field} in ({delete_ids_string})"
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
            self.logger.debug("Inserting new records...")
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
            self.logger.debug("Applying updates to existing records...")
            self.processUpdates()

        final_total = int(arcpy.management.GetCount(target_fc).getOutput(0))
        self.logger.info(f"Number of rows in target after changes applied: {final_total}")

        expected_total = count_target - count_deletes + count_inserts
        if expected_total != final_total:
            diff = expected_total - final_total
            self.logger.warning(
                f"Expected total of {expected_total} does not match actual final total {final_total}. Out by {diff}"
            )

    @timing_decorator
    def processUpdates(self):
        """ 
        Applies updates from the source to the target.
        The source is a changeset with a __change__ field.
        The target is expected to have the same schema.
        """ 
        self.logger.info(f"In the processUpdates function!")

        source = str(self.changeset_fc)
        target = str(self.layer_feature_class)

        source_desc = arcpy.da.Describe(source)
        target_desc = arcpy.da.Describe(target)

        source_fields = [field.name.lower() for field in source_desc.get("fields")]
        target_fields = [field.name.lower() for field in target_desc.get("fields")]

        self.logger.debug(f"Source fields: {source_fields}")
        self.logger.debug(f"Target fields: {target_fields}")

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
                record_id = row[source_fields.index(self.id_field)]
                updates_dict[record_id] = row
        del cursor 

        # Use a single UpdateCursor to apply updates in bulk
        with arcpy.da.UpdateCursor(in_table=target, field_names=target_fields) as updateCursor:
            for r in updateCursor:
                record_id = r[target_fields.index(self.id_field)]
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


    def deleteFeaturesNotIntersectingExtent(self, fc):
        """
        Delete all features in the given feature class that
        don't intersect the extent.
        """
        if fc is None:
            return 

        self.getExtentGeometry()
        if self.extent_geometry is None:
            return

        self.logger.info(f"Deleting all feature that don't intersect the extent")
        self.logger.info(fc)
        lyr = arcpy.management.MakeFeatureLayer(
            in_features=str(fc), out_layer="temp_layer"
        )
        arcpy.management.SelectLayerByLocation(
            lyr,
            overlap_type="INTERSECT",
            select_features=str(self.extent_featureclass),
            invert_spatial_relationship="INVERT",
        )
        arcpy.management.DeleteRows(lyr)
        arcpy.Delete_management(lyr)
        return


    def deleteFeaturesNotMatchingSQL(self, fc):
        """
        Delete all features in the given feature class that
        don't match the given SQL where_clause.
        """
        if fc is None:
            return 
        if self.sql_filter is None:
            return
        self.logger.info(f"Deleting all features that don't match the given SQL expression")
        lyr = arcpy.management.MakeFeatureLayer(
            in_features=str(fc), out_layer="temp_layer"
        )
        arcpy.management.SelectLayerByAttribute(
            in_layer_or_view=lyr, where_clause=sql_filter, invert_where_clause="INVERT"
        )
        arcpy.management.DeleteRows(lyr)
        arcpy.Delete_management(lyr)
        return


    def convertIdFieldToInteger(self, fc):
        """
        LINZ primary key fields are listed on their website as integer,
        but in the exported file geodatabase are sometimes double.
        Also, the conversion from geojson to feature class interprets the number
        as a float too.
        This function converts a field to an integer data type.
        Without doing this, the upsert process doesn't correctly match
        identifiers.
        """
        self.logger.info(f"Converting {self.id_field} to integer type in {fc}")
        fc = str(fc)
        fields = [f for f in arcpy.ListFields(fc) if f.name == self.id_field]
        if len(fields) == 0:
            self.logger.warning(f"Could not find {self.id_field} in {fc}. Unable to convert id field.")
            return
        field = fields[0]
        if field.type not in ("Double", "Float", "Integer", "SmallInteger"):
            self.logger.warning(
                f"{self.id_field} not a number field in {fc}, cannot convert to integer"
            )
            return
        if field.type == "Integer":
            self.logger.info(
                f"{self.id_field} is already an integer data type, no need to convert the data type"
            )
            arcpy.management.AddIndex(
                in_table=fc,
                fields=self.id_field,
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
            expression=f"!{self.id_field}!",
            expression_type="PYTHON3",
            code_block="",
            field_type="TEXT",
            enforce_domains="NO_ENFORCE_DOMAINS",
        )
        arcpy.management.DeleteField(
            in_table=fc, drop_field=self.id_field, method="DELETE_FIELDS"
        )
        arcpy.management.AddField(
            in_table=fc,
            field_name=self.id_field,
            field_type="LONG",
            field_is_nullable="NULLABLE",
            field_is_required="NON_REQUIRED",
        )
        arcpy.management.AddIndex(
            in_table=fc,
            fields=self.id_field,
            index_name="id_idx2",
            unique="UNIQUE",
            ascending="NON_ASCENDING",
        )
        arcpy.management.CalculateField(
            in_table=fc,
            field=self.id_field,
            expression=f"!{temp_fieldname}!",
            expression_type="PYTHON3",
            code_block="",
            field_type="TEXT",
            enforce_domains="NO_ENFORCE_DOMAINS",
        )
        arcpy.management.DeleteField(
            in_table=fc, drop_field=temp_fieldname, method="DELETE_FIELDS"
        )

        self.logger.info(f"Finished converting id field to integer.")
        return fc

    def update_last_updated_file(self, update_time=None):
        """
        Updates the last_updated.json file for the
        current configuration being processed.
        update_time is an ISO date string in UTC.
        """
        if isinstance(update_time, datetime):
            update_time = f"{update_time.isoformat()}Z"
        else:
            update_time = f"{datetime.utcnow().isoformat()}Z"

        with open(self.last_updated_file, "w") as file:
            json.dump({"last_updated": update_time}, file)
        self.logger.info(f"The last updated file has been set to: {update_time}")
        return

    def getExtentGeometry(self):
        """
        Fetch the first record from the extent_featureclass
        in the staging file geodatabase.
        """
        if self.extent_geometry is not None:
            return self.extent_geometry

        extent_records = [
            row[0] for row in arcpy.da.SearchCursor(str(self.extent_featureclass), ["SHAPE@"])
        ]
        if len(extent_records) == 0:
            self.extent_geometry = None
        else:
            self.extent_geometry = extent_records[0]
        return self.extent_geometry

    def geometryToGeojson(self, in_geometry):
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

    def purgeChangesets(self):
        """
        Delete old changesets, retain the last number
        as specified by retain_after_purge configuration setting.
        """
        if not self.retain_after_purge:
            logger.info("No retain_after_purge number specified, skipping purge.")
            return

        # Delete changeset json files
        self.logger.info("Purging old changeset json files")        
        json_files = list(self.changeset_directory.glob("*.json"))
        json_files.sort(key=lambda x: os.path.getctime(x), reverse=True)
        files_to_delete = json_files[self.retain_after_purge:]
        for file in files_to_delete:
            try:
                file.unlink()  # Delete the file
                self.logger.debug(f"Deleted: {file}")
            except Exception as e:
                self.logger.warning(f"Error deleting {file}: {e}")

        # Delete full download zip files
        self.logger.info("Purging old full download zip files")
        full_directory = self.layer_data_directory / "full"
        zip_files = list(full_directory.glob("*.zip"))
        zip_files.sort(key=lambda x: os.path.getctime(x), reverse=True)
        files_to_delete = zip_files[self.retain_after_purge:]
        for file in files_to_delete:
            try:
                file.unlink()  # Delete the file
                self.logger.debug(f"Deleted: {file}")
            except Exception as e:
                self.logger.warning(f"Error deleting {file}: {e}")

        # Delete changeset feature classes
        staging_fgb = self.layer_data_directory / self.staging_fgb_name
        arcpy.env.workspace = str(staging_fgb)
        feature_classes = arcpy.ListFeatureClasses()

        # Filter feature classes that contain "changeset" in their names
        self.logger.info("Purging old changeset feature classes")
        changeset_feature_classes = [fc for fc in feature_classes if "changeset" in fc]
        changeset_feature_classes.sort()
        feature_classes_to_delete = changeset_feature_classes[:-self.retain_after_purge]
        for fc in feature_classes_to_delete:
            try:
                arcpy.Delete_management(fc)
                self.logger.debug(f"Deleted: {fc}")
            except Exception as e:
                self.logger.warning(f"Error deleting {fc}: {e}")
        return

    @staticmethod
    def geometryToBboxString(in_geometry):
        """
        Convert a geometry to a BBOX string.
        XMin,YMin,XMax,YMax,EPSG:wkid
        """
        in_geometry = in_geometry.projectAs(arcpy.SpatialReference(4326))
        extent = in_geometry.extent
        bbox_string = f"{extent.XMin},{extent.YMin},{extent.XMax},{extent.YMax},EPSG:{extent.spatialReference.factoryCode}"
        return bbox_string

    @staticmethod
    def slugify(text):
        """
        Convert a string to a safe string that can
        be used as a folder or file name.
        """
        if text is None or not isinstance(text, str):
            return text
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
        return text

    @staticmethod
    def ensure_folder(folder):
        """Create a folder if it doesn't exist"""
        if isinstance(folder, str):
            folder = Path(folder)
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)

def main(args):
    """
    Takes the given arguments and calls the necessary functions
    to process the request.
    """

    linz_dataset = init(args=args)
    if not linz_dataset:
        logger.info(
            f"Please review config file and update before running again."
        )
        exit()

    if linz_dataset.action == ActionToTake.INIT:
        linz_dataset.prepare()
        logger.info(f"Init for {linz_dataset.config_name} is complete. Please update the configuration file and optionally the extent feature class.")
        return

    if linz_dataset.action == ActionToTake.REQUESTDOWNLOAD:        
        linz_dataset.requestDownload()
    if linz_dataset.action == ActionToTake.DOWNLOADEXPORT:
        linz_dataset.download_export()    
    if linz_dataset.action == ActionToTake.PROCESSFULLDOWNLOAD:
        linz_dataset.processFullDownload()

    if linz_dataset.action == ActionToTake.REQUESTCHANGESET:
        linz_dataset.requestChangeset()
    if linz_dataset.action == ActionToTake.PROCESSJSONCHANGESET:
        linz_dataset.processChangeSet()

    logger.info(f"Finished")
    return


if __name__ == "__main__":
    logger = configureLogging(logs_directory)
    logger.setLevel(logging.DEBUG)
    parser = argparse.ArgumentParser(
        prog="LINZ WFS",
        description="Python script to download LINZ datasets to ArcGIS feature class and keep updated using changesets.",
    )
    parser.add_argument(
        "-n",
        "--name",
        help="A user specified friendly name for this download. Use file and folder friendly text, avoid special characters and spaces.",
    )
    parser.add_argument(
        "-i",
        "--init",
        action="store_true",
        help="Flag to initialise a data folder, create config file and staging.gdb but don't download anything.",
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
        "-r", "--resume", help="Resume polling for a previous full export attempt."
    )
    parser.add_argument(
        "-lf",
        "--localfull",
        help="Process an already downloaded zip file. Provide the full path to the zip file with this option.",
    )
    parser.add_argument(
        "-lc",
        "--localchangeset",
        help="Process an already downloaded changes json file. Provide the full path to the json file with this option.",
    )

    args = parser.parse_args()
    main(args)
