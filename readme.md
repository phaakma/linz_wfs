# LINZ WFS Download Script  

Author: Paul Haakma  
Created: June 2024   

## Purpose  
This Python script simplifies the task of downloading LINZ datasets to an ArcGIS feature class, including applying changesets to an existing dataset.  

## Requirements  
1. Python >3.x environment.  
2. arcpy (i.e. typically either ArcGIS Pro or ArcGIS Server).  
3. Sufficient disk storage for temporary files.  

## Basic Installation and Setup  
1. As a minimum, copy the LINZ_WFS.py and LINZ_WFS.bat files to a directory of your choice.    
2. Run the script once (either from the batch file or by running the python file directly) and it will create any missing directories, create a settings.json file if it doesn't exist and create a sample config file in the config directory.  
3. Update the API key in the settings.json file.
4. Optionally, specify paths for config, data and logs.  

Refer to the LINZ_WFS_documentation.md file in the documentation folder for more in depth instructions.  