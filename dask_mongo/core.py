from copy import deepcopy
from math import ceil
from typing import Dict

import dask
import dask.bag as db
import pymongo
from dask import delayed
from distributed import get_client


@delayed
def write_mongo(
    values,
    connection_args,
    database,
    collection,
):
    with pymongo.MongoClient(**connection_args) as mongo_client:
        database_ = mongo_client.get_database(database)
        # NOTE: `insert_many` will mutate its input by inserting a "_id" entry.
        # This can lead to confusing results, so we make a deepcopy to avoid this.
        database_[collection].insert_many(deepcopy(values))


def to_mongo(
    bag: db.Bag,
    *,
    connection_args: Dict,
    database: str,
    collection: str,
    compute_options: Dict = None,
):
    """Write a Dask Bag to a Mongo database.

    Parameters
    ----------
    bag:
      Dask Bag to write into the database.
    connection_args:
      Connection arguments to pass to ``MongoClient``.
    database:
      Name of the database to write to. If it does not exists it will be created.
    collection:
      Name of the collection within the database to write to.
      If it does not exists it will be created.
    compute_options:
      Keyword arguments to be forwarded to ``dask.compute()``.
    """
    if compute_options is None:
        compute_options = {}

    partitions = [
        write_mongo(partition, connection_args, database, collection)
        for partition in bag.to_delayed()
    ]

    try:
        client = get_client()
    except ValueError:
        # Using single-machine scheduler
        dask.compute(partitions, **compute_options)
    else:
        return client.compute(partitions, **compute_options)


@delayed
def fetch_mongo(
    connection_args,
    database,
    collection,
    id_min,
    id_max,
    match,
    include_last=False,
):
    with pymongo.MongoClient(**connection_args) as mongo_client:
        database_ = mongo_client.get_database(database)

        results = list(
            database_[collection].aggregate(
                [
                    {"$match": match},
                    {
                        "$match": {
                            "_id": {
                                "$gte": id_min,
                                "$lte" if include_last else "$lt": id_max,
                            }
                        }
                    },
                ]
            )
        )

    return results


def read_mongo(
    connection_args: Dict,
    database: str,
    collection: str,
    chunksize: int,
    match: Dict = {},
):
    """Read data from a Mongo database into a Dask Bag.

    Parameters
    ----------
    connection_args:
      Connection arguments to pass to ``MongoClient``.
    database:
      Name of the database to write to. If it does not exists it will be created.
    collection:
      Name of the collection within the database to write to.
      If it does not exists it will be created.
    chunksize:
      Number of elements desired per partition.
    match:
      Dictionary with match expression. By default it will bring all the documents in the collection.
    """

    with pymongo.MongoClient(**connection_args) as mongo_client:
        database_ = mongo_client.get_database(database)

        nrows = next(
            (
                database_[collection].aggregate(
                    [
                        {"$match": match},
                        {"$count": "count"},
                    ]
                )
            )
        )["count"]

        npartitions = int(ceil(nrows / chunksize))

        partitions_ids = list(
            database_[collection].aggregate(
                [
                    {"$match": match},
                    {"$bucketAuto": {"groupBy": "$_id", "buckets": npartitions}},
                ],
                allowDiskUse=True,
            )
        )

    partitions = [
        fetch_mongo(
            connection_args,
            database,
            collection,
            partition["_id"]["min"],
            partition["_id"]["max"],
            match,
            include_last=idx == len(partitions_ids) - 1,
        )
        for idx, partition in enumerate(partitions_ids)
    ]

    return db.from_delayed(partitions)
