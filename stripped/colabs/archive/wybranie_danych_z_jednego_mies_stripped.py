!apt-get install openjdk-8-jdk-headless -qq > /dev/null
!wget -q dlcdn.apache.org/spark/spark-3.5.0/spark-3.5.0-bin-hadoop3.tgz
!tar xf spark-3.5.0-bin-hadoop3.tgz
!pip install -q findspark

import os
os.environ["JAVA_HOME"] = "/usr/lib/jvm/java-8-openjdk-amd64"
os.environ["SPARK_HOME"] = "/content/spark-3.5.0-bin-hadoop3"

import findspark
findspark.init()

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.types import IntegerType, FloatType, StringType, StructType
from google.colab import drive

from pyspark.sql.types import IntegerType, FloatType, StringType, StructType

import pandas as pd

spark = SparkSession.builder\
        .master("local")\
        .appName("Colab")\
        .config('spark.ui.port', '4050')\
        .getOrCreate()

drive.mount('/content/drive')

columns = ['lon', 'lat', 'Date', 'SWdown', 'LWdown', 'SWnet', 'LWnet', 'Qle', 'Qh', 'Qg', 'Qf', 'Snowf', 'Rainf', 'Evap', 'Qs', 'Qsb', 'Qsm', 'AvgSurfT', 'Albedo', 'SWE', 'SnowDepth', 'SnowFrac', 'SoilT_0_10cm', 'SoilT_10_40cm', 
           'SoilT_40_100cm', 'SoilT_100_200cm', 'SoilM_0_10cm', 'SoilM_10_40cm', 'SoilM_40_100cm', 'SoilM_100_200cm', 'SoilM_0_100cm', 'SoilM_0_200cm', 'RootMoist', 'SMLiq_0_10cm', 'SMLiq_10_40cm', 'SMLiq_40_100cm', 'SMLiq_100_200cm', 
           'SMAvail_0_100cm', 'SMAvail_0_200cm', 'PotEvap', 'ECanop', 'TVeg', 'ESoil', 'SubSnow', 'CanopInt', 'ACond', 'CCond', 'RCS', 'RCT', 'RCQ', 'RCSOL', 'RSmin','RSMacr', 'LAI', 'GVEG', 'Streamflow']

# Utworzenie schematu określającego typ zmiennych
schema = StructType()
for i in columns:
  if i == "Date":
    schema = schema.add(i, StringType(), True)
  else:
    schema = schema.add(i, FloatType(), True)

# Wczytanie zbioru Nasa w sparku
nasa = spark.read.format('csv').option("header", True).schema(schema).load('/content/drive/MyDrive/BigMess/NASA/NASA.csv')

nasa.createOrReplaceTempView("nasa")

nasa = spark.sql("""
    SELECT
        CAST(SUBSTRING(CAST(Date AS STRING), 1, 4) AS INT) AS Year,
        CAST(SUBSTRING(CAST(Date AS STRING), 5, 2) AS INT) AS Month,
        n.*
    FROM nasa n
    """)

nasa = nasa.drop("Date")
nasa.show(5)

nasa_dec22_loc = nasa.where((nasa.Year==2022) & (nasa.Month==12))

nasa_dec22_loc = nasa_dec22_loc.toPandas()

nasa_dec22_loc = nasa_dec22_loc.groupby(['lon', 'lat']).size().reset_index(name='count')
max_count = nasa_dec22_loc['count'].max()
max_count

nasa_dec22_loc = nasa_dec22_loc.drop('count', axis=1)

nasa_dec22_loc.to_csv('/content/drive/MyDrive/BigMess/NASA/nasa_dec22_loc.csv', index=False)


