SELECT DISTINCT
    c.collection_name,
    c.collection_id,
    c.collection_type
FROM {collection_members_nodes} AS c
WHERE c.cmdb_id = %s
UNION
SELECT DISTINCT
    c.collection_name,
    c.collection_id,
    c.collection_type
FROM {collection_members_pods} AS c
WHERE c.cmdb_id = %s
UNION
SELECT DISTINCT
    c.collection_name,
    c.collection_id,
    c.collection_type
FROM {collection_members_containers} AS c
WHERE c.cmdb_id = %s
LIMIT %s;
