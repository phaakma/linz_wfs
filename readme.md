# LINZ WFS Download Script  

Author: Paul Haakma  
Created: June 2024   

## Purpose  
This Python script simplifies the task of downloading LINZ vector datasets to an ArcGIS feature class and subsequently applying changesets.  
This script is written to deliberately target the data available from the LINZ Data Service.  
The script is provided AS IS with no warantee, guarantee or support of any type. Use is entirely at your own risk.  

## Requirements  
1. Python >3.x environment.  
2. ArcPy (i.e. typically either ArcGIS Pro or ArcGIS Server).  
4. Sufficient disk storage for temporary files.  

>Tested with Python 3.11.8. Should work with earlier Python 3 version, but please test first.  
>Tested with ArcGIS Pro v3.3. Should work with ArcPy from earlier versions but please test first.  

## Explanation  
The script has two flows - one uses the LINZ export API to download a full dataset and the other uses the LINZ WFS feed to download changeset data. A settings file holds configurations which allow to specify the details for multiple LINZ datasets. The script has several predefined command line arguments which control which flow is used. The two most common are --download and --changeset which launch into those two flows. A download must be run at least once on a particular dataset before a changeset can be run. Another download can be run at any time to overwrite with a full download of the data.  
The data ends up in a staging file geodatabase, and it is your responsibility to propagate it elsewhere from there.  

## Basic Installation and Setup  
1. Copy the LINZ_WFS.py and run.bat files to a directory of your choice. Change into that directory. 
2. In the run.bat file, check the python path and update it if necessary according to your environment.   
3. Make a copy of the template.cnf file in this directory and rename it settings.cnf.      
5. Obtain a LINZ API key. Paste this into the settings.cnf file for the api_key property.  
6. Look up the LINZ layer id and the name of the primary key field for the layer you wish to download. Add a new section to your settings.cnf using a file friendly name. Update with the layer id and id field.  
7. Optionally, add the path to a feature class, Esri json file or shape file in the settings.cnf for the extent_path to restrict the download to a polygon feature. 
8. Run the following command: "run.bat --name **config_name** --download"  
9. Schedule the following command: "run.bat --name **config_name** --changeset --purge"    

### Smoketest  
1. Follow the basic installation steps above.
2. Navigate to the data directory. Check there is a new folder named the same as your **config_name**.  
3. Navigate into that directory.
4. Assuming you have run the "download" option, check there is a "full" folder that has a zip file in it containing the zipped file geodatabase from LINZ.  
5. If you have run the "changeset" option, check there is a "changeset" folder that will have a json file containing geojson of any changes. Note that if you run the download and then the changeset immediately there will likely be no changes.  
6. Check there is a "last_updated.json" file.
7. Check there is a staging.gdb file geodatabase.
8. Open the staging.gdb in ArcGIS Pro.
9.  Check there is a feature class called "layer_xxxxxx" which contains the full download.
10. Check there is a feature class called "layer_xxxxxx_changeset_xxxxxxx" which contains a changeset, if one has been processed.
11. Check there is a polygon feature class called "extent". It will be empty at first.

### Directory Structure  
The following diagram shows the directory structure. The data and log directories are created as subdirectories in the folder where the script is located unless a different data location is specified in the settings.cnf file. You can move these directories at any time and update the path in the configuration file.

```
Parent Folder  
| LINZ_WFS.py
| run.bat
| LINZ_WFS_batch_logs.log
| data
|  |  config_name
|  |   | staging.gdb
|  |   | last_updated.json
|  |   | full
|  |   |   | layer_xxxxx.zip
|  |   | changesets
|  |   |   | layer_xxxxx_xxxxxxx.json
| logs
|  |  logfile.log  

```
## Settings file  
Each section in the configuration file is prefixed by the name of the section enclosed in square brackets.  

### Default section  
At the top, there is a special DEFAULT section. These values are used unless overridden by a specific section. The only value that must be updated is the LINZ api key.    
```
[DEFAULT]
api_key = xxxxxxxxx     # REQUIRED: your LINZ API key  
data_directory =        # OPTIONAL: defaults to a subfolder called data.
http_proxy =            # OPTIONAL: http proxy path 
https_proxy =           # OPTIONAL: https proxy path 
retain_after_purge = 5  # OPTIONAL: defaults to 5 
initial_buffer = 1000   # OPTIONAL: defaults to 1000
poll_interval = 10      # OPTIONAL: defaults to 10
max_polling_time = 600  # OPTIONAL: defaults to 600
wkid = 2193             # OPTIONAL: defaults to 2193 (NZTM)
extent_path =           # OPTIONAL: a polygon feature for the extent

``` 
 
>NOTE: Windows file paths should use double backslashes. Don't use quotation marks.

- api_key - Required. A valid LINZ api key. This key must be manually scoped for "Query layer data", "Full access to tables and layers" and "Full access to data exports".
- data_directory - Optional. A path to the data folder. Ensure that there is enough disk space in this location to hold the staging data and implement cleanup processes as necessary. Ensure the user account running the process has read and write access to this folder.    
- http_proxy and https_proxy - Optional. Only use this if the server that the process is running on is required to use a forward proxy for all requests and you are required the manually route the traffic to that proxy. Otherwise you can either delete the proxies section completely from the settings file or just set each value to an empty string. **NOTE: proxy should work but has not been tested.**  
- retain_after_purge - When the --purge argument is used, the script will retain this number of full download zip files and changeset files and delete the rest. Defaults to 5.
- initial_buffer - see the Extent section below. Defaults to 1000m.  
- poll_interval - Optional. How long in seconds between polling LINZ to see if a requested export is ready for download. Defaults to 10 seconds. If this is a large dataset and you know it will always take a long time, there is no harm in leaving it at 10 seconds but there is also little point in polling every 10 seconds, so perhaps consider overriding this to 30 or 60 seconds for specific datasets.   
- max_polling_time - Optional. How long in seconds the script will keep polling LINZ to see if a requested export is ready for download. Defaults to 600 seconds. Consider increasing this in the individual sections for large datasets.  
- wkid - The ESPG well-known identifier. Defaults to 2193 (NZTM).  
- extent_path - Optional. A path to either a feature class in a geodatabase, an Esri json file or a shape file. This should be a polygon geometry with just one record. The first record retrieved will be used as the extent for download, and only features intersecting the polygon will be in the final output. Refer the section below for more information on Extents.  

### Dataset sections  

Sections names are free text but should be file and folder friendly so don't use special characters.  

A section requires the section name inside square brackets to identify the section, and a LINZ layer id and the LINZ primary id field name. This information can be found on the LINZ website [data.linz.govt.nz](https://data.linz.govt.nz). Any of the DEFAULT section values can be added inside the section and will be used over the default values.

```
[rail_station_points]
layer_id = 50318
id_field = t50_fid
```  
> NOTE: Yes, you can create multiple configurations for the same LINZ layer if you wish, just create multiple sections with different names. E.g. you could download Auckland property titles to one folder and Christchurch property titles to a different folder.  


- layer_id - The LINZ layer id.
- id_field - Every LINZ layer has a unique id field. This field is important because the changeset logic relies on using this to work out which records to update. You should verify this via the metadata available for the layer at the LINZ LDS website and specify it here. 
- sql_filter - Optional. This parameter allows to specify an attribute filter query. 
- cql_filter - Optional. This parameter allows to specify an attribute filter query.  

## Extent and Filters   
You can provide an extent and/or filters to narrow down the final output. Since we are using a combination of the LINZ Export API and WFS, there are some nuances to setting these up. The main one being to ensure you also include a sql filter if you specify a cql filter in the configuration if you wish to filter by attribute. See below for more information.  

### Extent
An **extent_path** can provided in the setting.cnf file, either in the default section and/or specifically in individual sections. This should be a path to a feature class in a geodatabase, an Esri json file or a shape file. An Esri json file is ideal because it involves just one text based file that can be easily copied. The geometry should be a polygon, and there should only be one record. The first record retrieved is used.  

If a crop geometry is provided for a full data export then the LINZ API literally crops any features. This is not always desirable, for example it may result in clipped property title geometries which could be confusing. To get around this, during a full download, the extent geometry is buffered by the initial_buffer amount (defaults to 1000 meters) and the extent of that used, then a select is run on the downloaded data and anything not intersecting the actual extent geometry is deleted. The 1000m buffer works most of the time, but in some fringe cases with extremely large polygons such as national parks this buffer will not be enough. If you know this to be the case, it is recommended to adjust your extent polygon to capture known areas. Otherwise you can also increase the **initial_buffer** size in the config.json.  

The LINZ WFS API works differently in that if a BBOX is specified it performs an intersect instead of cropping. The extent of the geometry is used as the BBOX, and then a select is run on the downloaded data and anything not intersecting the actual extent geometry is deleted.  

### SQL Filters
The Export API doesn't appear to have an option for an attribute filter, only the extent crop. This means that the initial exported file geodatabase **always** includes all records within the extent. The WFS API accepts CQL and OGC filters, but cannot accept both a BBOX and a CQL filter at the same time. OGC filters are XML based. All this makes it hard to define one filter that can used in all requests and also easily converted to SQL for use in ArcPy if necessary too.    

This script takes a simple approach: any extent provided is used in the requests, then if a "sql_filter" is provided in the configuration then once the data (both full downloads and changesets) is copied to the staging file geodatabase, a select is performed using the sql filter and anything not matching that expression is deleted. This SQL expression should be a valid expression that ArcPy can run on the data. 

Admittedly, this means the WFS request may download slightly more data that necessary. For example, if you just wanted Freehold titles for the entire country, you end up downloading all titles each time and then discarding the ones you don't need. If you prefer, the script does cater for using a CQL filter. If you provide a "cql_filter" expression in the section within the settings.cnf file, the WFS request will use that **instead** of the BBOX for the request. If there is an extent geometry then the downloaded data will still be spatially filtered by that geometry afterwards. This approach may or may not be more efficient for your use case. E.g. from the previous example, you could use a CQL filter to download all Freehold properties for the entire country, and then any not intersecting your extent geometry would be deleted. 
If you provide a "cql_filter" then you should also provide an equivalent "sql_filter" too.   

> In practice, so long as you check regularly, changesets are usually relatively small no matter which approach you take, which is why the simplified approach of just using the SQL filter is usually sufficient.  

> More info on ECQL can be found here:    
[GeoServer ECQL Reference](https://docs.geoserver.org/stable/en/user/filter/ecql_reference.html)  

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
Following are all the possible command line arguments and options.
All arguments have a short and a long variant. It is recommended to use the long variant as this is more user friendly for future users of your scripts. 

### -n --name  
This is the only argument that is required every time. It is used to create the subdirectory for a given configuration where the data is written to. The name should be added as a section in the settings.cnf prior to using it. Avoid special characters and spaces.   
```
run.bat **--name nzproperty** --init 
``` 
### -i --init  
A flag used to initialise the data directory for a new configuration. Requires --name.  
```
run.bat --name nzproperty **--init**  
``` 
### -d --download
A flag used to request a full download.   
``` 
run.bat --name nzproperty **--download**  
```  
### -c --changeset  
A flag used to request a changeset.  
``` 
run.bat --name nzproperty  **--changeset**  
```  
### -p --purge  
A flag used to request that old json files, downloaded zip files and old changeset feature classes be deleted. The "retain_after_purge" option in the configuration file determines how many old files are kept.  
```
run.bat --name nzproperty --changeset **--purge**  
``` 
### -r --resume  
Resume polling for a previous full export attempt. If you initiated a full download, but it never downloaded, you can use the LINZ export id to resume and download it. 
A full download is an asynchronous request. This means that a request is sent to LINZ to generate a zip file, and then the script repeatedly checks to see if it is ready to download. If the max_polling_time is reached the script will exit without downloading, but LINZ will continue generating the export and eventually it will be ready. The time it takes depends on the size of the requested data and how busy the LINZ servers are.  
If this happens, check the logs and you will see the export id noted at the time of the initial request. Use this export id number with the --resume flag to resume polling for that same export.
> 2024-06-29 13:11:15,794 - INFO - 488 - Export id is: 3534442  
 
For very large datasets that may take a long time to generate, it is recommended that you use this resume option if possible rather than starting a new export request which would unnecessarily strain the LINZ servers.  
If you identify a dataset that does take a long time, you can increase the maximum polling time by adding a **max_polling_time** in seconds for that section in the settings.cnf file.  
``` 
run.bat --name nzproperty **--resume 3534442**  
``` 
### -lf --localfull  
Process an already downloaded zip file from LINZ.  
The zip file that this script downloads is exactly the same one that you get if you manually create an export using the LINZ website. If you prefer, you can manually download the data and copy it to the data directory, then use the --localfull option to process that data.
> NOTE: If you manually download the data, then the "last_updated.json" file may not have the correct datetime recorded as it doesn't know when you downloaded the data. Manually update this file to the correct datetime before requesting a changeset. 
``` 
run.bat --name nzproperty **--localfull "L:\\LINZ\\data\\nzproperties\\full\\my_download.zip"**  
```  
### -lc --localchangeset  
Process an already downloaded changes json file. 
Probably only used in rare occassions such as if the script unexpectely crashed after downloading the changes json file and before it got processed. High risk here of getting the data out of sync though, so if you are unsure it would be recommended at this point to instead run the --download option and just reset the entire dataset.
Provide the full path to the json file with this option.
``` 
run.bat --name nzproperty **--localchangeset "L:\\LINZ\\data\\nzproperties\\changeset\\layer_50804_20241126T041155.json"**  
```  

## Logging  
Logs are stored in a subfolder relative to where the python script is stored called "logs".   

However, since the script is primarily intended to be run unattended, there are some errors that may cause the python script or terminal window to crash which may not be captured by the logger. The run.bat file was created to aid with troubleshooting. The batch file pipes all logger.info output and std_error output to another file called "LINZ_WFS_batch_logs.log" in the main script directory. 
This file is appended each time the script is run. This makes two things to be aware of:  
1. This file contains output from **every** run, so there may be messages relating to different configurations. For this reason, avoid running multiple configurations concurrently, or re-write your own batch file accordingly.  
2. This file will grow over time. You may wish to periodically delete it if there are no issues to note within the log file.   

One of your first troubleshooting steps should be to check the two different logging files for error messages.  

## FAQ, Use Cases and Considerations  

### Troubleshooting tip  
Any flaw in the request to the LINZ WFS service will result in an error message rather than the geojson data. Since this response is streamed directly to the layer data directory as a json file, try opening up that json file to see what is in it. If it is an xml type response, look for error messages in it to help troubleshoot further.  

### What if my dataset drifts out of sync with LINZ?  
For small datasets, using the changesets might not be justified in the first place - just download the entire dataset each time and you will never experience this issue.  
For large datasets with lots of changes, you may find it out of sync with LINZ over time. This could be because the script failed occasionally due to issues such as network conditions, disk space, RAM, outages and all sorts of other things outside of your control. If you suspect this is the case, run using the --download option to reset the data to a current copy from LINZ. This is recommended to do periodically anyway (perhaps annually or more often depending on your use case).  

### Differences to existing WFSDownload python script  
There is an existing python script that has been around since 2015 and is widely used still. If you use this and it meets your needs then there is no need to change it to this script. This script was created to take advantage of the LINZ export api and because the author preferred a different structure to the downloaded data.  
Some noteable changes:  
- Use of command line arguments to create a more opinionated and direct workflow.  
- Use of configuration files and configparser makes it a easier to understand and define the configuration parameters being used. The configuration file keeps all the config together in one file separated by sections, allows defaults that can be overridden as well as the use of comments should you wish to leave verbose notes for your successor.     
- A defined structure for output data directories and staging file geodatabases.    
- Included batch file makes it easy to implement. Run from command line or schedule with Windows Task Scheduler. The batch file also streams output to a separate log file, so that if the actual Windows process crashes for any reason, there is still output for troubleshooting.  
- Different approach to applying changeset. The WFSDownload script would delete existing records that were to be updated and reappend in the new ones. This script updates records in place.  

### This script or FME?  
Your choice. Use the tools you have available and are most comfortable with. Those with FME tend to use it as first choice. If you don't have FME, or want to schedule this in an environment that has ArcPy but not FME then this script could be a good choice.  

### What if I don't have ArcGIS?  
This script was written with ArcGIS users in mind and relies on having ArcPy. Having said that, a lot of the code doesn't actually require ArcPy, such as the actual downloading the raw geojson data, so feel free to dive into the code and extract out any parts that may be useful elsewhere.  

## Suggested Enhancements  

> Add ability to download plain tables. Currently it expects a spatial layer.  
> Add a history table to the staging file geodatabase that populates whenever run. Currently you can browse the logs to see the history but it would be useful to see a simple summary in a table. Could have things like: datetime of update, number of adds, updates and deletes.  
> Make the target geodatabase a parameter in the settings.cnf. Currently each layer has a separate staging file geodatabase and a separate process need to copy it elsewhere. But some users might prefer a single target file geodatabase, or an enterprise geodatabase.  
