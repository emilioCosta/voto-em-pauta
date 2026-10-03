PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    dataset_slug TEXT NOT NULL,
    dataset_title TEXT NOT NULL,
    resource_id TEXT NOT NULL UNIQUE,
    resource_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL,
    metadata_modified TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    election_year INTEGER NOT NULL,
    tse_candidate_id TEXT NOT NULL,
    state_code TEXT,
    office TEXT,
    full_name TEXT,
    ballot_name TEXT,
    party_code TEXT,
    party_name TEXT,
    ballot_number TEXT,
    registration_status TEXT,
    registration_detail TEXT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    UNIQUE (election_year, tse_candidate_id)
);

CREATE TABLE IF NOT EXISTS candidate_social_links (
    id INTEGER PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    state_code TEXT,
    order_number TEXT,
    url TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    UNIQUE (candidate_id, state_code, order_number, url)
);

CREATE TABLE IF NOT EXISTS declared_assets (
    id INTEGER PRIMARY KEY,
    election_year INTEGER NOT NULL,
    tse_candidate_id TEXT NOT NULL,
    item_number TEXT,
    item_type TEXT,
    description TEXT,
    declared_value TEXT,
    source_id INTEGER NOT NULL REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS candidacy_history (
    id INTEGER PRIMARY KEY,
    current_candidate_id TEXT NOT NULL,
    election_year INTEGER NOT NULL,
    state_code TEXT,
    office TEXT,
    candidate_name TEXT,
    ballot_name TEXT,
    party_code TEXT,
    party_name TEXT,
    registration_status TEXT,
    judgment_status TEXT,
    result_status TEXT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    UNIQUE (current_candidate_id, election_year, state_code, office, party_code)
);

CREATE TABLE IF NOT EXISTS source_rows (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    member_name TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE (source_id, member_name, row_number)
);

CREATE TABLE IF NOT EXISTS proposal_documents (
    id INTEGER PRIMARY KEY,
    election_year INTEGER NOT NULL,
    state_code TEXT NOT NULL,
    file_name TEXT NOT NULL,
    archive_path TEXT NOT NULL,
    archive_member TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    UNIQUE (source_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_candidates_election ON candidates(election_year, state_code, office);
CREATE INDEX IF NOT EXISTS idx_assets_candidate ON declared_assets(election_year, tse_candidate_id);
CREATE INDEX IF NOT EXISTS idx_history_candidate ON candidacy_history(current_candidate_id, election_year);
CREATE INDEX IF NOT EXISTS idx_source_rows_source ON source_rows(source_id);
