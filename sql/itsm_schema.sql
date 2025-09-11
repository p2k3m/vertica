CREATE SCHEMA IF NOT EXISTS itsm;
CREATE SCHEMA IF NOT EXISTS cmdb;

CREATE TABLE IF NOT EXISTS itsm.incident (
  id VARCHAR(32) PRIMARY KEY,
  opened_at TIMESTAMP,
  priority VARCHAR(8),
  category VARCHAR(64),
  assignment_group VARCHAR(64),
  short_desc VARCHAR(256),
  description VARCHAR(2000),
  status VARCHAR(32),
  closed_at TIMESTAMP,
  ci_id VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS itsm.change (
  id VARCHAR(32) PRIMARY KEY,
  requested_at TIMESTAMP,
  window_start TIMESTAMP,
  window_end TIMESTAMP,
  risk VARCHAR(16),
  status VARCHAR(32),
  description VARCHAR(2000),
  ci_id VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS cmdb.ci (
  id VARCHAR(32) PRIMARY KEY,
  name VARCHAR(128),
  class VARCHAR(32),
  environment VARCHAR(16),
  owner VARCHAR(128),
  criticality VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS cmdb.ci_rel (
  parent_ci VARCHAR(32),
  relation VARCHAR(32),
  child_ci VARCHAR(32)
);
