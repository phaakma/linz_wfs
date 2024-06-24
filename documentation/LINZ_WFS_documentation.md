# LINZ WFS Download Script  

Author: Paul Haakma  
Created: June 2024   

## Purpose  
This Python script simplifies the task of downloading LINZ datasets to an ArcGIS feature class, including applying changesets to an existing dataset.  
Whilst the underlying code could be used to download data from any compatible WFS service, this script is written to deliberately target the data available from the LINZ Data Service via WFS. 

## Requirements  
1. Python >3.x environment.  
2. arcpy (i.e. typically either ArcGIS Pro or ArcGIS Server).  
4. Sufficient disk storage for temporary files.  

>Tested with Python 3.11.8. Should work with earlier Python 3 version, but please test first.  
>Tested with ArcGIS Pro v3.3. Should work with arcpy from earlier versions but note that arcpy.management.Append GP tool requires upsert option.

## Basic Installation and Setup  
1. As a minimum, copy the LINZ_WFS.py and LINZ_WFS.bat files to a directory of your choice.    
2. Run the script once (either from the batch file or by running the python file directly) and it will create any missing directories, create a settings.json file if it doesn't exist and create a sample config file in the config directory.  
3. Update the API key in the settings.json file.
4. Optionally, specify paths for config, data and logs.
5. Create a config file for the layer you want.  

> NOTE: Read the Target Feature Class section below for the recommended workflow for setting up a target feature class.  

### Smoketest  
1. Run "LINZ_WFS.bat sample.json".  
2. Navigate to the data/layer_50318/AllNZRailStationPoints folder (i.e. the equivalent data folder).
3. Check there is a json file containing the raw downloaded LINZ data.  
4. Check there is a json file called "_last_updated.json" and that it contains the datetime in UTC that you downloaded the data.  
5. Check there is a staging.gdb file geodatabase.  
6. Open the staging.gdb file geodatabase in ArcGIS Pro.  
7. Check there is a feature class in the staging.gdb called "layer_50318".
8. Add the feature class to a map and check it has all the Railway Station points for NZ.  

If this is all as expected then you can go ahead and configure a config file of your own.  

### Directory Structure  
The following image shows the default directory structure if no directory locations are specified in the settings.json file. The config, data and log directories are created as subdirectories in the folder where the script is located. Otherwise, the locations specified in the settings.json file are used.  
LINZ layers all have an ID number. E.g. NZ Property Titles is 50804. The script creates a subdirectory in the data folder based on the layer id being processed. Additionally, each config has an "output_feature_class_name" which is used to create yet another subdirectory which holds the actual downloaded data and a staging file geodatabase.
>NOTE: This allows you to create separate configurations for the same layer. For example: you could create a config that downloads the property titles for the Waikato and a second separate config file for the BOP property titles. The directory structure would then be a parent data folder called "layer_50804" and two subdirectories called "Waikato" and "BOP", each with their own staging.gdb file geodatabase.  

```
Parent Folder  
| LINZ_WFS.py
| LINZ_WFS.bat
| config  
|  |  layerconfig.json  
| data
|  |  layer_xxxxx
|  |   |  <Name of dataset>
|  |   |   | staging.gdb
|  |   |   | layer_xxxxxx_20240619_0900.json
| logs
|  |  LINZ_WFS.py_last_run.log
|  |  logfile.log 


```
## Settings file  
Example settings.json file. The config, data and logs values are all optional. Either delete those lines or leave them set to an empty string ("") to just let the script create subdirectories relative to the script itself.  
>NOTE: Windows file paths should use double backslashes.


```
{ 
    "api_key": "xxxxxxxxxxxxxxxxxxxxxx",
    "config": "C:\\linz\\config",
    "data": "",
    "logs": "",
    "proxies": {
        "http": "http://proxy.example.com:8080",
        "https": "http://secureproxy.example.com:8090"
    }
}
```  

- api_key - A valid LINZ api key.  
- config - A path to the config folder. This is where the config files for each dataset you wish to download reside. Ensure the user account running the process has read access to this folder.  
- data - A path to the data folder. Each download will end up in a subdirectory of this folder. The raw download stream plus a staging file geodatabase for each dataset will reside under this directory. Ensure that there is enough disk space in this location to hold the staging data and/or implement cleanup processes as necessary. Ensure the user account running the process has read and write access to this folder.  
- logs - A path to the logs folder. Logs will be written to this folder. Ensure the user account running the process has read and write access to this folder.   
- proxies - Optional. Only use this is the server that the process is running on is required to use a forward proxy for all requests and you are required the manually route the traffic to that proxy. Otherwise you can either delete the proxies section completely from the settings file or just set each value to an empty string.  

## Configuration files  
Configuration files define parameters for a download of a particular LINZ layer.  

Example:
```
{
    "id_field": "id",
    "config_name": "MatamataRailStationPoint",
    "target_feature_class": "L:\\LINZ\\data\\LINZ.gdb\\nzproperties",
    "cql_filter": "land_district='Otago'",
    "wfs_request_params": {
        "typename": "layer-50318",
        "srsname": "EPSG:2193",
        "bbox": "1836922,5805529,1848188,5816795,EPSG:2193",
        "cql_filter": "name='Matamata Station'"
    }
}
```

- id_field - Every LINZ layer has a unique id field. This field is important because the changeset logic relies on using this to work out which records to update. You should verify this via the metadata available for the layer at the LINZ LDS website and specify it here.  
- config_name - This is a user friendly title you choose for this configuration. It may be used as a folder or feature class name, so you may notice it updated by the script (slugified) to be suitable. As a general good practice, **avoid** special characters, starting with digits or using spaces.
- target_feature_class - Optional. If specified, once the script has finished downloading and processing to the staging.gdb file geodatabase, it will then also update this target_feature_class. Refer the section "Target Feature Class".  

The **"wfs_request_parameters"** section contains the parameters that will be passed through to the LINZ WFS web service to request the download.  
> NOTE: Yes, you can research what other available parameters would work and experiment with adding them here.  
- typename - this is the layer identifier. For LINZ this will be the prefiex "layer-" followed by the layer id. E.g. "layer-50804".
> NOTE: If you want the changeset for a layer, just add the suffix "-changeset" to your typename. E.g. "layer-50804-changeset".  
- srsname - this is the spatial reference. Use the prefix "EPSG:" followed by the wkid. In NZ this will typically be NZTM. E.g. "EPSG:2193".  
- bbox - Optional. This parameter defines a bounding box within which to download the data. This should be in the following format: "XMin,YMin,XMax,YMax,EPSG:wkid". In other words, specify the lower left coordinates then the upper right.  
- cql_filter - Optional. This parameter allows to specify an attribute filter query to be applied to the download parameters.

> NOTE: bbox and cql_filter cannot be used together! Only use one or the other. There are more advanced filtering parameters you can use too. For more information on LINZ filters, refer to the LINZ documentation:  
> [LINZ WFS filter methods and parameters](https://www.linz.govt.nz/guidance/data-service/linz-data-service-guide/web-services/wfs-filter-methods-and-parameters)

## Target Feature Class  
The configuration file being called can optionally include a "target_feature_class" value which should be the full path to a feature class in either a file geodatabase or an enterprise geodatabase.  
If this is not included, then the script will end after it finishes downloading the data and converting it to a feature class in the staging gdb file geodatabase. 
However, if a target is specified, it will also attempt to apply the update to this target feature class. This target can be in another file geodatabase or an enterprise geodatabase. If it is an enterprise geodatabase, then the path must include the sde file, and the sde file will determine the credentials (and optionally the version) used.  
The logic used for updating the target is fairly straight forward:
- If the download is a full download (i.e. doesn't have 'changeset' in the layer id/typename), then the script will truncate the target and append all data back in. 
> **Warning**: If the target is versioned or has attachments enabled, then it will use arcpy.management.DeleteRows instead of arcpy.management.TruncateTable. DeleteRows is much slower than TruncateTable, and therefore this should be avoided if possible. In this case, downloading changesets is the recommended workflow.  
- If the download is a changeset, then the script first deletes records in the target that have been tagged for deletion, then performs and upsert using the arcpy.management.Append tool, specifying the match field as the LINZ id field.  

This workflow is suitable for most cases. But if you have more complex requirements, you could choose to not specify a target and just let the script populate the feature classes in the staging file geodatabase. Then you could create your own workflow to pull either the newly updated main feature class or the changeset feature class from the staging.gdb into your target. This could be achieved using other python scripts, FME or other ETL tool of your choice.  

> NOTE: The recommended workflow to create your target feature class is to manually visit https://data.linz.govt.nz and use the export tools to download a copy of the data as a file geodatabase. This will give you a full snapshot of the data at that point in time in a feature class using the LINZ specified field types. Copy this feature class to the file geodatabase or enterprise geodatabase where you want the final data to reside.  

## Changesets  
LINZ provides a changeset service for each layer. Each layer has an id, for example the NZ Property Titles is 50804. To download the full data for that layer you would use "layer-50804" in the configuration file. However, you can instead download the changeset by adding the suffix "-changeset", e.g. "layer-50804-changeset".  
The key part here is something that the script does behind the scenes. A changeset request needs to know a "to" and "from" datetime to generate the changeset records from. The script always uses "right now" as the "to" datetime. The "from" datetime is tracked using a file in each data directory called "_last_updated.json".  
### Example:  
```
{"last_updated": "2024-06-20T01:31:30.245Z"}
```
If this file does not exist when a full layer download is requested then it is created and the datetime is set to the time of the download. If this file exists when another full layer download is requested then it is overwritten with new details.  
If this file does not exist when a changeset download is requested then the script aborts as it does not know when to start. If this file exists, the datetime is read in, used as the "from" datetime to request changes and then the file is overwritten with the datetime of this download.  
The typical workflow for setting up to use a changeset would look like this:
1. Create a configuration file that downloads the full layer.
2. Run the script once manually using this configuration file.
3. Create a second configuration file that downloads the changeset for that layer.
4. Schedule a task to run using this changeset configuration file periodically.  

At any time in the future, you can manually the the full layer download configuration file and it will delete the existing full data layer and recreate it. Then you can resume using the changeset configuration.  

> NOTE: If you manually download the intial full download and intend to use changesets moving forward, you will need to manually create the _last_updated.json file for the initial run. Set the datetime to either the time you manually downloaded the data. 

## FAQ, Use Cases and Considerations  

### Troubleshooting  
The most common problem would be a flaw in the configuration file causing the LINZ WFS service to send an error message rather than the geojson data. Since this response is streamed directly to the layer data directory as a json file, try opening up that json file to see what is in it. If it is an xml type response, look for error messages in it to help troubleshoot further.  

### Data types  
The WFS json data that is downloaded is a geojson FeatureCollection. The data types in this data are not strongly typed. The arcpy.conversion.JSONToFeatures GP tool is used to convert this to a feature class. This tool attempts to infer the data types but may not always get it right. E.g. integers may be interpreted as doubles.  
The feature classes in the staging file geodatabase will always be these automatically inferred data types.  
This is one key reason why you should manually set up the target feature class. If you specify a target for the script, it uses the standard Append GP tool with schema_type="NO_TEST" and field_mapping=None. This will attempt to match fields and will autocast where possible. But in certain cases it may fail. If this is the case, you could NOT specify a target, and instead incorporate your own ETL workflow to take either the main data layer or the changeset from the staging gdb and apply it to a target of your choice, dictating the data typing and data mapping in that process. 
The recommended approach can be to use the LINZ LDS website to export and manually download a file geodatabase, and then use this as the basis for your final target feature class. This will ensure your target matches the data types that LINZ define.   

> Can the intial download be scripted? In theory yes, there is an API for creating and downloading exports. However, at the time of writing there seems to be a bug in the API, where if using an API key it treats the POST request to create an export as a GET request which doesn't work. If this is resolved in the future I may look at automating that initial download into this script. However, keep in mind that if your final target needs to reside in a specific location such as an enterprise geodatabase, you will always need to manually set up that target anyway. Also, generating the initial export of a large dataset such as Property Titles is a server intensive task that can take a long time, and there is an argument to be made that manually performing this step is better than automating it. Automation can lead to inadvertant overuse which would impact LINZ systems and is not desirable.  

### Indexes  
It is recommended to create an attribute index on the identifier field in your target feature class.  

### Large datasets  
Most LINZ datasets can usually be downloaded fine using this script, but for very large datasets such as NZ Property TItles, if the data stream gets interupted at any point whilst downloading then you would have to start the process again.   
The recommended approach is to manually export the intial data, and then use this script for just the changesets moving forward.    
> NOTE: Versioning your target dataset for large datasets is not recommended.  

### What if my dataset drifts out of sync with LINZ?  
For small datasets, using the changesets might not be justified. Just download the entire dataset each time.  
For large datasets with lots of changes, you may find it out of sync with LINZ. This could be because the script failed occasionally due to issues such as network conditions, disk space, RAM, outages and all sorts of other things outside of your control. If you suspect this is the case, you have a couple of options.  
1. Start afresh. Usually the best way and recommended to do periodically anyway (perhaps annually or more depending on your use case).  
2. Run a brute change detection process between a clean copy and your target feature class. You might choose to do this if your target is versioned and a full delete/append is not desirable. There are Python scripts and FME tools that can do this sort of comparison.

### Clean up of old download files  
The script does not do any clean up of old download files. This is deliberate as user's use cases will differ - some may want to retain them forever, others may have disk storage constraints and want to only keep the last few, or you may want to implement some backup workflow to zip the json files up to store them elsewhere (being text files, zipping the files does save a lot of space). 
It is up to you to implement the workflow of your choice to clean up old download files.  

### Differences to existing WFSDownload python script  
There is an existing python script that has been around since 2015 and is widely used still. If you use this and it meets your needs then there is no need to change it to this script. This script was created mainly because the author preferred a different structure to the downloaded data and took the opportunity to use some newer or different methods and also to write up this documentation to help users understand the workflow and to implement.  
Some noteable changes:  
- Use of Json configuration files makes it a easier to understand and define the configuration parameters being used. (NB: Yaml would have been preferred since it allows comments, but the default Python environments in ArcGIS didn't have the yaml module installed by default. Just using Json seemed more preferable than requiring users to amend the Python environment, which can be challenging in an ArcGIS Server environment).  
- A workflow more targeted at LINZ downloads. In particular, a clearer approach to working with the changesets.  
- Different folder structure, including separating out config, data and logs into different subdirectories.  
- Included batch file makes it easy to implement. Run from command line or schedule with Windows Task Scheduler. The batch file also streams output to a separate log file, so that if the actual Windows process crashes for any reason, there is still output for troubleshooting.  
- Different approach to applying changeset. The WFSDownload script would delete existing records that were to be updated and reappend in the new ones. The arcpy.management.Append GP tool now has an upsert option that can apply updates automatically based on the id field. This is a better approach especially when the target is a versioned dataset.

### This script or FME?  
Your choice. Use the tools you have available and are most comfortable with. Those with FME tend to use it as first choice. If you don't have FME, or want to schedule this in an environment that has ArcPy but not FME then this script could be a good choice.  

### What if I don't have ArcGIS?  
This script was written with ArcGIS users in mind and relies on having ArcPy. Having said that, the code up to the end of downloading the raw geojson data doesn't actually require ArcPy, so feel free to dive into the code and extract that part to use.  

## Process Diagram  

![Initial Download](process_diagram.svg)


