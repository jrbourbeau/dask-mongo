import pymongo
from pymongo import MongoClient
import json 
from typing import Dict
import pandas as pd

import dask
import dask.dataframe as dd

#write to mongo db 



def check_db_exists(client, db):
    db_names = client.list_database_names()

    try:
        db in db_names
    except ValueError:
        print(f"The database {db} doesn not exists")
        return 


def write_mongo(
    df_partition,  #this is a delayed object
    db,
    coll, 
):
    documents = df_partition.compute().to_dict("records") #is there a way of avoiding the compute in here? 

    db[coll].insert_many(documents)


def to_mongo(
    df,
    connection_args: Dict, 
    database: str, #name of data base
    coll: str,    #name of collection
):

    mongo_client = MongoClient(**connection_args)

    #we should check that the database exists probably
    check_db_exists(mongo_client, database)

    #get database
    db = mongo_client.get_database(database)

    #convert df to dict -> do we convert to json and then dicst? 
    dask.compute(
        [write_mongo(partition, db, coll) for partition in df.to_delayed()]
    )

    