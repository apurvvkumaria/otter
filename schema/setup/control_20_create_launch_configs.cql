USE @@KEYSPACE@@;

-- Desired underlying structure is for the row key to be
-- the account ID, the column key to be the group ID, with
-- the data contained as JSON
--
-- In CQL3, the primary key is split such that the first part
-- ends up in the row key, the rest of the key ends up
-- as a composite column key.
--
-- This does a good job of making things a bit more rational
-- than some of the CQL2 ecentricity.
--
-- My mother, who cut her teeth in those heady days of IMS
-- and mainframe computers, before Codd's relational model
-- will probably get the giggles looking at this.

CREATE COLUMNFAMILY launch_config (
    "tenantId" ascii,
    "groupId" ascii,
    data ascii,
    PRIMARY KEY("tenantId", "groupId")
) WITH compaction = {
    'class' : 'SizeTieredCompactionStrategy',
    'min_threshold' : '2'
} AND gc_grace_seconds = 3600;
