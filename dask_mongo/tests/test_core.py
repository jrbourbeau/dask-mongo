import subprocess

import dask.dataframe as dd
import pandas as pd
import pymongo
import pytest
from dask.dataframe.utils import assert_eq
from distributed import Client, wait
from distributed.utils_test import gen_cluster

from dask_mongo import read_mongo, to_mongo


@pytest.fixture
def connection_args(tmp_path):
    port = 27016
    with subprocess.Popen(
        ["mongod", f"--dbpath={str(tmp_path)}", f"--port={port}"]
    ) as proc:
        connection_args = {
            "host": "localhost",
            "port": port,
        }
        yield connection_args
        proc.terminate()


@gen_cluster(client=True, clean_kwargs={"threads": False})
async def test_to_mongo(c, s, a, b, connection_args):
    df = pd.DataFrame({"a": range(10), "b": range(10, 20)})
    npartitions = 3
    ddf = dd.from_pandas(df, npartitions=npartitions)

    with pymongo.MongoClient(**connection_args) as mongo_client:
        db_name = "test-db"
        assert db_name not in mongo_client.list_database_names()
        collection_name = "test-collection"

        partitions = to_mongo(
            ddf,
            connection_args=connection_args,
            database=db_name,
            collection=collection_name,
        )
        assert len(partitions) == npartitions
        await wait(partitions)

        assert db_name in mongo_client.list_database_names()
        assert [collection_name] == mongo_client[db_name].list_collection_names()

        result = pd.DataFrame.from_records(
            mongo_client[db_name][collection_name].find()
        )
        result = result.drop(columns=["_id"]).sort_values(by="a").reset_index(drop=True)
        assert_eq(ddf, result)


def test_to_mongo_single_machine_scheduler(connection_args):
    df = pd.DataFrame({"a": range(10), "b": range(10, 20)})
    ddf = dd.from_pandas(df, npartitions=3)

    with pymongo.MongoClient(**connection_args) as mongo_client:
        db_name = "test-db"
        assert db_name not in mongo_client.list_database_names()
        collection_name = "test-collection"

        to_mongo(
            ddf,
            connection_args=connection_args,
            database=db_name,
            collection=collection_name,
        )

        assert db_name in mongo_client.list_database_names()
        assert [collection_name] == mongo_client[db_name].list_collection_names()

        result = pd.DataFrame.from_records(
            mongo_client[db_name][collection_name].find()
        )
        result = result.drop(columns=["_id"]).sort_values(by="a").reset_index(drop=True)
        assert_eq(ddf, result)


def test_read_mongo(connection_args):
    client = Client()  # noqa: F841

    df = pd.DataFrame({"a": range(10), "b": range(10, 20)})
    ddf = dd.from_pandas(df, npartitions=3)

    with pymongo.MongoClient(**connection_args):
        db_name = "test-db"
        collection_name = "test-collection"

        partitions = to_mongo(
            ddf,
            connection_args=connection_args,
            database=db_name,
            collection=collection_name,
        )

        wait(partitions)

        rm_ddf = read_mongo(
            connection_args=connection_args,
            database=db_name,
            collection=collection_name,
            chunksize=20,
        )

        rm_ddf.compute()

        result = rm_ddf.drop(columns=["_id"]).sort_values(by="a").reset_index(drop=True)

        assert_eq(ddf, result, check_index=False, check_divisions=False)


def test_mongo_roundtrip_single_machine_scheduler(connection_args):
    df = pd.DataFrame({"a": range(10), "b": range(10, 20)})
    ddf = dd.from_pandas(df, npartitions=3)

    with pymongo.MongoClient(**connection_args):
        db_name = "test-db"
        collection_name = "test-collection"

        to_mongo(
            ddf,
            connection_args=connection_args,
            database=db_name,
            collection=collection_name,
        )

        # read whole dataframe, match={} is default
        rm_ddf = read_mongo(
            connection_args=connection_args,
            database=db_name,
            collection=collection_name,
            chunksize=20,
        )

        result = rm_ddf.drop(columns=["_id"]).sort_values(by="a").reset_index(drop=True)

        assert_eq(ddf, result, check_index=False, check_divisions=False)
