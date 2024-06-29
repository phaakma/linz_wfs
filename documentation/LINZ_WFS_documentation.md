# LINZ WFS Download Script  

Author: Paul Haakma  
Created: June 2024   

## Purpose  
This Python script simplifies the task of downloading LINZ vector datasets to an ArcGIS feature class and applying changesets.  
Whilst the underlying code could be used to download data from any compatible WFS service, this script is written to deliberately target the data available from the LINZ Data Service via WFS. 

## Requirements  
1. Python >3.x environment.  
2. ArcPy (i.e. typically either ArcGIS Pro or ArcGIS Server).  
4. Sufficient disk storage for temporary files.  

>Tested with Python 3.11.8. Should work with earlier Python 3 version, but please test first.  
>Tested with ArcGIS Pro v3.3. Should work with ArcPy from earlier versions but note that the arcpy.management.Append GP tool requires upsert option.

## Basic Installation and Setup  
1. Copy the LINZ_WFS.py and run.bat files to a directory of your choice.  
2. In the run.bat file, check the python path and update it if necessary.  
3. Obtain a LINZ API key. 
4. Look up the LINZ layer id and the name of the primary key field for that layer.
5. Open a command prompt and change the directory to where you have stored the script.
6. Run the following command: "run.bat --name **config_name** --init --layer **layer_id** --field **field_name**" (replace **config_name** with a descriptive name for this configuration, and **layer_id** and **field_name** with the layer id and primary key field from the previous step).
7. Update the API key in the settings.json file that is created in the script directory.
8. Optionally, tweak the config.json file that is created in the directory for this configuration.
9. Optionally, add an extent record to the "extent" feature class in the staging.gdb file geodatabase.  
10. Run the following command: "run.bat --name **config_name** --download  
11. Schedule the following command: "run.bat --name **config_name** --changeset --purge"    

### Smoketest  
1. Follow the basic installation steps above.
2. Navigate to the data directory. Check there is a new folder named the same as your **config_name**.  
3. Navigate into that directory.
4. Assuming you have run the "download" option, check there is a "full" folder that has a zip file in it containing the zipped file geodatabase from LINZ.  
5. If you have run the "changeset" option, check there is a "changeset" folder that will have a json file containing geojson of any changes. Note that if you run the download and then the changeset immediately there will likely be no changes.  
6. Check there is a "config.json" file.  
7. Check there is a "last_updated.json" file.
8. Check there is a staging.gdb file geodatabase.
9. Open the staging.gdb in ArcGIS Pro.
10. Check there is a feature class called "layer_xxxxxx" which contains the full download.
11. Check there is a feature class called "layer_xxxxxx_changeset_xxxxxxx" which contains a changeset, if one was processed.
12. Check there is a polygon feature class called "extent". It will be empty at first.

### Directory Structure  
The following diagram shows the directory structure. The data and log directories are created as subdirectories in the folder where the script is located unless different locations are specified in the settings.json file. You can move these directories at any time and update the path in the settings.json file.

```
Parent Folder  
| LINZ_WFS.py
| run.bat
| data
|  |  config_name
|  |   | staging.gdb
|  |   | config.json
|  |   | last_updated.json
|  |   | full
|  |   |   | layer_xxxxx.zip
|  |   | changesets
|  |   |   | layer_xxxxx_xxxxxxx.json
| logs
|  |  LINZ_WFS.py_last_run.log
|  |  logfile.log 


```
## Settings file  
Example settings.json file. 
```
{ 
    "api_key": "xxxxxxxxxxxxxxxxxxxxxx",
    "config": "C:\\linz\\config",
    "data": "",
    "logs": "",
    "proxies": {
        "http": "http://proxy.example.com:8080",
        "https": "http://secureproxy.example.com:8090"
    },
    "max_polling_time": 600,
    "poll_interval": 10
}
``` 
 
>NOTE: Windows file paths should use double backslashes.

- api_key - A valid LINZ api key. This key must be manually scoped for "Query layer data", "Full access to tables and layers" and "Full access to data exports".
- data - Optional. A path to the data folder. Ensure that there is enough disk space in this location to hold the staging data and implement cleanup processes as necessary. Ensure the user account running the process has read and write access to this folder.  
- logs - Optional. A path to the logs folder. Logs will be written to this folder. Ensure the user account running the process has read and write access to this folder.   
- proxies - Optional. Only use this if the server that the process is running on is required to use a forward proxy for all requests and you are required the manually route the traffic to that proxy. Otherwise you can either delete the proxies section completely from the settings file or just set each value to an empty string. 
- max_polling_time - Optional. How long in seconds the script will keep polling LINZ to see if a requested export is ready for download. Defaults to 600 seconds. Consider increasing this for large datasets.    
- poll_interval - Optional. How long in seconds between polling LINZ to see if a requested export is ready for download. Defaults to 10 seconds. If this is a large dataset and you know it will always take a long time, there is no harm in leaving it at 10 seconds but also little point in polling every 10 seconds, so perhaps consider increasing this to 30 or 60 seconds.   

## Configuration files  
Configuration files define parameters for a download of a particular LINZ layer. The intial run of run.bat with the --init flag will create a subdirectory in the data directory for this configuration, and create a config.json file which you can alter if necessary.    

Example:
```
{
    "layer_id": "50804",
    "wkid": "2193",
    "id_field": "id",
    "cql_filter": "land_district='Otago'",
    "target_feature_class": "L:\\LINZ\\data\\LINZ.gdb\\nzproperties",    
    "retain_after_purge": 2,
    "initial_buffer": 1000
}
```

- layer_id - The LINZ layer id.
- wkid - the ESPG code for the data to be downloaded in. Defaults to NZTM (2193).
- id_field - Every LINZ layer has a unique id field. This field is important because the changeset logic relies on using this to work out which records to update. You should verify this via the metadata available for the layer at the LINZ LDS website and specify it here.  
- cql_filter - Optional. This parameter allows to specify an attribute filter query to be applied to the download parameters.
- target_feature_class - Optional. If specified, once the script has finished downloading and processing to the staging.gdb file geodatabase, it will then also update this target_feature_class. Refer the section "Target Feature Class".  
- retain_after_purge - refer to section below on the --purge option.
- initial_buffer - refer to section below on Extent.  

## Extent and Filters   
You can provide an extent and/or filters to narrow down the final output. Since we are using a combination of the LINZ Export API and WFS, there are some nuances to setting these up. The main one being to ensure you include both a sql and a cql filter in the config.json if you wish to filter by attribute. See below for more information.  

### Extent
The initial run will create a staging.gdb file geodatabase in the data configuration directory, and will create a polygon feature class in it called "extent". The feature class will be in NZTM.  
Use of this is optional. If no extent is created, then any download or changeset request will not apply any spatial filtering.  
If you want to filter the data spatially, insert one record into this extent feature class.

If a crop geometry is provided for a full data export then the LINZ API literally crops any features. This is not always desirable, for example it may result in clipped property title geometries which could be confusing. To get around this, during a full download, the extent geometry is buffered by the initial_buffer amount (defaults to 1000 meters) and the extent of that used, then a select is run on the downloaded data and anything not intersecting the actual extent geometry is deleted. The 1000m buffer works most of the time, but in some fringe cases with extremely large polygons such as national parks this buffer will not be enough. If you know this to be the case, it is recommended to adjust your extent polygon to capture known areas. Otherwise you can also increase the initial_buffer size in the config.json.  

The LINZ WFS API works differently in that if a BBOX is specified it performs and intersect instead of cropping. The extent of the geometry is used as the BBOX, and then a select is run on the downloaded data and anything not intersecting the actual extent geometry is deleted.  

### SQL Filters
The Export API doesn't appear to have an option for an attribute filter, only the extent crop. This means that the initial exported file geodatabase **always** includes all records within the extent. The WFS API accepts CQL and OGC filters, but cannot accept both a BBOX and a CQL filter at the same time. OGC filters are XML based. All this makes it hard to define one filter that can used in all requests and also easily converted to SQL for use in ArcPy if necessary too.    

This script takes a simple approach: any extent provided is used in the requests, then if a "sql_filter" is provided in the config.json, then once the data (both full downloads and changesets) is copied to the staging file geodatabase, a select is performed using the sql filter and anything not matching that expression is deleted. This SQL expression should be a valid expression that ArcPy can run on the data. 

Admittedly, this means the WFS request may download slightly more data that necessary. For example, if you just wanted Freehold titles for the entire country, you end up downloading all titles each time and then discarding the ones you don't need. If you prefer, the script does cater for using a CQL filter in the config.json. If you provide a "cql_filter" expression in the config.json file, the WFS request will use that **instead** of the BBOX for the request. If there is an extent geometry then the downloaded data will still be spatially filtered by that geometry afterwards. This approach may or may not be more efficient for your use case. E.g. from the previous example, you could use a CQL filter to download all Freehold properties for the entire country, and then any not intersecting your extent geometry would be deleted. 
If you provide a "cql_filter" then you should also provide an equivalent "sql_filter" too.   

> In practice, changesets are usually relatively small no matter which approach you take, which is why the simplified approach of just using the SQL filter is usually sufficient.  

> More info on ECQL can be found here:    
[GeoServer ECQL Reference](https://docs.geoserver.org/stable/en/user/filter/ecql_reference.html)  

## Target Feature Class  
The configuration file can optionally include a "target_feature_class" value which should be the full path to a feature class in either a file geodatabase or an enterprise geodatabase.  
If this is not included, then the script will end after it finishes downloading the data and converting it to a feature class in the staging gdb file geodatabase. 
However, if a target is specified, it will also attempt to apply the update to this target feature class. If it is an enterprise geodatabase, then the path must include the sde file, and the sde file will determine the credentials (and optionally the version) used.  
The logic used for updating the target is straight forward:
- If a full download was requested, then the script will truncate the target and append all data back in. 

> **Warning**: If the target is versioned or has attachments enabled, then it will use arcpy.management.DeleteRows instead of arcpy.management.TruncateTable. DeleteRows is much slower than TruncateTable, and therefore this should be avoided if possible. In this case, downloading changesets is the recommended workflow.  

- If a changeset was requested, then the script first deletes records in the target that have been tagged for deletion, then performs an upsert using the arcpy.management.Append tool, specifying the match field as the LINZ id field.  

This workflow is suitable for most cases. If you have more complex requirements, you could choose to not specify a target and just let the script populate the feature classes in the staging file geodatabase. Then you could create your own workflow to pull either the newly updated main feature class or the changeset feature class from the staging.gdb into your target. This could be achieved using other python scripts, FME or other ETL tool of your choice.  

> NOTE: The append assumes that the arcpy.management.Append tool can automatically match the fields. You can use a copy of the feature class originally downloaded from LINZ as the template for your own target feature class to ensure they will match.  

## Changesets  
LINZ provides a changeset service for each layer. To download a changeset, use the --changeset option.   
A changeset request needs to know a "to" and "from" datetime to generate the changeset records from. The script always uses "right now" as the "to" datetime. The "from" datetime is tracked using a file in each data directory called "last_updated.json".  
### Example:  
```
{"last_updated": "2024-06-20T01:31:30.245Z"}
```
If this file does not exist when a full download is requested then it is created and the datetime is set to the time of the download. If this file exists when a subsequent full download is requested then it is overwritten with new details.  
If this file does not exist when a changeset is requested then the script creates the file using the current datetime then aborts as there was no start time to query. If this file exists, the datetime is read in, used as the "from" datetime to request changes and then the file is overwritten with the datetime of this new changeset download.  

At any time in the future, you can use the --download option to re-download a new copy of the data. Then you can resume using the changeset option.  

## Command Line Arguments and Options  
Following are all the possibly command line arguments and options.
All arguments have a short and a long variant. It is recommended to use the long variant as this is more user friendly for future users of your scripts. 

### -n --name  
This is the only argument that is required every time. It is used to create the subdirectory for a given configuration and therefore in subsequent runs it identifies which folder to read in the configuration from and write any data to. Avoid special characters and spaces.  
> --name nzproperty

### -i --init  
A flag used to initialise a new configuration. Requires --name, --layer and --field.

### -l --layer  
Used when initialising a new configuration, is a LINZ layer id. Is written into the config.json file so is not required to be used after the initial command.  
> --layer 50804  

### -f --field  
Used when initialising a new configuration, is the name of the unique primary key field as specified by LINZ. Look this up on the LINZ website. Used by the append tool when performing the upsert for updates.  
> --field id

### -w -wkid  
Used when initialising a new configuration, the wkid to be used to download the data in. If not specified it defaults to NZTM (2193).
> --wkid 2193 

### -d --download
A flag used to request a full download.   

### -c --changeset  
A flag used to request a changeset.

### -p --purge  
A flag used to request that old json files, downloaded zip files and old changeset feature classes be deleted. The "retain_after_purge" option in the config.json file determines how many old files are kept.

### -r --resume  
Resume polling for a previous full export attempt. If you initiated a full download, but it never downloaded, you can use the LINZ export id to resume and download it. 
A full download is an asynchronous request. This means that a request is sent to LINZ to generate a zip file, and then the script repeatedly checks to see if it is ready to download. If the max_polling_time is reached the script will exit without downloading, but LINZ will continue generating the export and eventually it will be ready. The time it takes depends on the size of the requested data and how busy the LINZ servers are.  
If this happens, check the logs and you will see the export id noted at the time of the initial request. Use this export id number with the --resume flag to resume polling for that same export.
> 2024-06-29 13:11:15,794 - INFO - 488 - Export id is: 3534442 

For very large datasets that may take a long time to generate, it is recommended that you use this resume option if possible rather than starting a new export request which would unnecessarily strain the LINZ servers.  
> --resume 3534442  

### -z --zip  
Process an already downloaded zip file from LINZ.  
The zip file that this script downloads is exactly the same one that you get if you manually create an export using the LINZ website. If you prefer, you can manually download the data and copy it to the data directory, then use the --zip option to process that data.
> NOTE: If you manually download the data, then the "last_updated.json" file may not have the correct datetime recorded as it doesn't know when you downloaded the data. Manually update this file to the correct datetime before requesting a changeset. 
 
> --zip "L:\\LINZ\\data\\nzproperties\\full\\my_download.zip"  

### Examples  

> run.bat --name nzproperty --init --layer 50804 --field id  
> run.bat --name nzproperty --download  
> run.bat --name nzproperty --changeset
> run.bat --name nzproperty --changeset --purge
> run.bat --name nzproperty --resume 3534442 
> run.bat --name nzproperty --zip "L:\\LINZ\\data\\nzproperties\\full\\my_download.zip"  

## Logging  
The python script uses a logger to write all logs down to the debug level to a file called logfile.log in the logs directory. If this file reaches 10MB in size then that file will be renamed and a new logfile.log file will be started.  
However, since this is intended to be run unattended, there are some errors that may cause the python script or terminal window to crash which may not be captured by the logger. To aid with troubleshooting, the batch file pipes all logger.info output and std_error output to another file called "LINZ_WFS.py_last_run.log" in the logs directory. This file is overwritten each time the script is run.  

One of your first troubleshooting steps should be to check the two different logging files for error messages.  

## FAQ, Use Cases and Considerations  

### Troubleshooting  
A flaw in the request to the LINZ WFS service will result in an error message rather than the geojson data. Since this response is streamed directly to the layer data directory as a json file, try opening up that json file to see what is in it. If it is an xml type response, look for error messages in it to help troubleshoot further.  

### Indexes  
It is recommended to create an attribute index on the identifier field in your target feature class.  

### What if my dataset drifts out of sync with LINZ?  
For small datasets, using the changesets might not be justified. Just download the entire dataset each time.  
For large datasets with lots of changes, you may find it out of sync with LINZ over time. This could be because the script failed occasionally due to issues such as network conditions, disk space, RAM, outages and all sorts of other things outside of your control. If you suspect this is the case, you have a couple of options.  
1. Run using the --download option. Usually the best way and recommended to do periodically anyway (perhaps annually or more depending on your use case).  
2. Run a brute change detection process between a clean copy and your target feature class. You might choose to do this if your target is versioned and a full delete/append is not desirable. There are Python scripts and FME tools that can do this sort of comparison.

### Differences to existing WFSDownload python script  
There is an existing python script that has been around since 2015 and is widely used still. If you use this and it meets your needs then there is no need to change it to this script. This script was created mainly because the author preferred a different structure to the downloaded data and took the opportunity to use some newer or different methods and also to write up this documentation to help users understand the workflow and to implement.  
Some noteable changes:  
- Use of command line arguments to create a more opinionated and direct workflow.  
- Use of Json configuration files makes it a easier to understand and define the configuration parameters being used. (NB: Yaml would have been preferred since it allows comments, but the default Python environments in ArcGIS didn't have the yaml module installed by default. Just using Json seemed more preferable than requiring users to amend the Python environment, which can be challenging in an ArcGIS Server environment).  
- Different folder structure, including separating out data configuration and logs into different subdirectories.  
- Included batch file makes it easy to implement. Run from command line or schedule with Windows Task Scheduler. The batch file also streams output to a separate log file, so that if the actual Windows process crashes for any reason, there is still output for troubleshooting.  
- Different approach to applying changeset. The WFSDownload script would delete existing records that were to be updated and reappend in the new ones. The arcpy.management.Append GP tool now has an upsert option that can apply updates automatically based on the id field. This is a better approach when the target is a versioned dataset.

### This script or FME?  
Your choice. Use the tools you have available and are most comfortable with. Those with FME tend to use it as first choice. If you don't have FME, or want to schedule this in an environment that has ArcPy but not FME then this script could be a good choice.  

### What if I don't have ArcGIS?  
This script was written with ArcGIS users in mind and relies on having ArcPy. Having said that, a lot of the code doesn't actually require ArcPy, such as the actual downloading the raw geojson data, so feel free to dive into the code and extract out any parts that may be useful elsewhere.  
