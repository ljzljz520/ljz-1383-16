-- Certificate / award evidence management
-- PostgreSQL 14+
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- Required for an exclusion constraint that combines certificate equality
-- with an overlapping timestamptz range.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- -------------------------------------------------------------------
-- Enumerations
-- -------------------------------------------------------------------
CREATE TYPE certificate_lifecycle_state AS ENUM (
  'not_active', 'valid', 'expired', 'revoked', 'disputed'
);

CREATE TYPE evidence_state AS ENUM (
  'self_reported',
  'reachable_unverified',
  'verified',
  'source_stale',
  'link_broken',
  'mismatch',
  'revoked_by_issuer',
  'historical_verified'
);

CREATE TYPE asset_role AS ENUM (
  'private_original', 'public_derivative', 'verification_snapshot', 'redaction_workfile'
);

CREATE TYPE asset_state AS ENUM (
  'uploaded', 'scanning', 'processing', 'derived', 'derivation_failed',
  'quarantined', 'deleted', 'revoked_marked'
);

CREATE TYPE certificate_event_type AS ENUM (
  'award.created',
  'certificate.renewed',
  'certificate.reissued',
  'certificate.revoked',
  'certificate.reinstated',
  'certificate.corrected',
  'asset.uploaded',
  'asset.replaced',
  'asset.derivation_failed',
  'issuer.renamed',
  'verification.checked',
  'verification.link_broken',
  'clock.correction_recorded'
);

-- -------------------------------------------------------------------
-- Issuers: rename is history, not a new identity
-- -------------------------------------------------------------------
CREATE TABLE issuers (
  issuer_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  current_name text NOT NULL,
  authority_type text NOT NULL,
  timezone text NOT NULL DEFAULT 'UTC',
  verification_base_url text,
  contact text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT issuer_timezone_tz CHECK (timezone IS NOT NULL)
);

CREATE TABLE issuer_name_history (
  issuer_name_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  issuer_id uuid NOT NULL REFERENCES issuers(issuer_id),
  name text NOT NULL,
  effective_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  reason text,
  source_url text,
  UNIQUE (issuer_id, effective_at, name)
);

-- -------------------------------------------------------------------
-- Certificate identities
-- The stable identity is independent from image replacements/renewals.
-- Sensitive raw values live in certificate_identity_fields, not this table.
-- -------------------------------------------------------------------
CREATE TABLE certificates (
  certificate_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  issuer_id uuid NOT NULL REFERENCES issuers(issuer_id),
  credential_type text NOT NULL,
  title text NOT NULL,
  normalized_identity_key text NOT NULL,
  achievement_count integer NOT NULL DEFAULT 1 CHECK (achievement_count = 1),
  current_state certificate_lifecycle_state NOT NULL DEFAULT 'not_active',
  evidence_state evidence_state NOT NULL DEFAULT 'self_reported',
  growth_goal text,
  public_note text,
  awarded_at timestamptz NOT NULL,
  expires_at timestamptz,
  expires_local_date date,
  expires_local_time time,
  expires_timezone text NOT NULL DEFAULT 'UTC',
  expiry_semantics text NOT NULL DEFAULT 'explicit_instant'
    CHECK (expiry_semantics IN ('explicit_instant', 'start_of_day', 'end_of_day', 'end_of_second')),
  revoked_effective_at timestamptz,
  revocation_reason text,
  version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT one_achievement_per_identity CHECK (achievement_count = 1),
  CONSTRAINT identity_key_unique UNIQUE (normalized_identity_key)
);

CREATE INDEX certificates_issuer_idx ON certificates (issuer_id);
CREATE INDEX certificates_current_state_idx ON certificates (current_state, expires_at);

-- Sensitive extracted fields are encrypted by the application before insert.
-- Hashes are for matching/deduplication only and must not be reversible IDs.
CREATE TABLE certificate_identity_fields (
  identity_field_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  field_name text NOT NULL,
  encrypted_value text NOT NULL,
  value_hash bytea NOT NULL,
  masked_value text NOT NULL,
  confidence numeric(5,4),
  extracted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (certificate_id, field_name)
);

CREATE INDEX identity_fields_hash_idx ON certificate_identity_fields (field_name, value_hash);

-- -------------------------------------------------------------------
-- Append-only event log
-- effective_at is business time; recorded_at is server receipt time.
-- -------------------------------------------------------------------
CREATE TABLE certificate_events (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  sequence_no bigint NOT NULL,
  event_type certificate_event_type NOT NULL,
  effective_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  actor_id uuid,
  idempotency_key text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  parent_event_id uuid REFERENCES certificate_events(event_id),
  UNIQUE (certificate_id, sequence_no),
  UNIQUE (idempotency_key)
);

CREATE INDEX certificate_events_effective_idx
  ON certificate_events (certificate_id, effective_at, sequence_no);

-- Explicit revision record for owner-entered facts such as title, growth goal,
-- issuer link and expiry interpretation. Immutable events retain full history;
-- this table gives the admin UI a convenient field-level audit trail.
CREATE TABLE certificate_revisions (
  revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  event_id uuid REFERENCES certificate_events(event_id),
  revised_by uuid,
  field_name text NOT NULL,
  old_value jsonb,
  new_value jsonb NOT NULL,
  change_reason text NOT NULL,
  revised_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX certificate_revisions_certificate_idx
  ON certificate_revisions (certificate_id, revised_at DESC);

-- Validity intervals are a transactionally maintained reduction of
-- award/renewal/reinstatement events. Revocation is evaluated separately
-- because it may arrive late and apply retroactively.
CREATE TABLE certificate_validity_periods (
  period_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  source_event_id uuid NOT NULL REFERENCES certificate_events(event_id),
  valid_from timestamptz NOT NULL,
  valid_to timestamptz NOT NULL,
  timezone text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT validity_interval_ordered CHECK (valid_from < valid_to),
  EXCLUDE USING gist (
    certificate_id WITH =,
    tstzrange(valid_from, valid_to, '[)') WITH &&
  )
);

CREATE INDEX validity_periods_lookup
  ON certificate_validity_periods (certificate_id, valid_from, valid_to);

-- -------------------------------------------------------------------
-- Files: private originals and public derivatives are separate objects
-- -------------------------------------------------------------------
CREATE TABLE assets (
  asset_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  role asset_role NOT NULL,
  state asset_state NOT NULL DEFAULT 'uploaded',
  storage_bucket text NOT NULL,
  storage_key text NOT NULL,
  public_url text,
  media_type text NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  sha256 bytea NOT NULL,
  is_public_current boolean NOT NULL DEFAULT false,
  parent_asset_id uuid REFERENCES assets(asset_id),
  redaction_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_code text,
  error_message text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  CONSTRAINT private_original_has_no_public_url CHECK (
    role <> 'private_original' OR public_url IS NULL
  ),
  CONSTRAINT public_current_requires_derivative CHECK (
    NOT is_public_current OR role = 'public_derivative'
  )
);

CREATE INDEX assets_certificate_state_idx ON assets (certificate_id, role, state);
CREATE UNIQUE INDEX assets_one_public_current
  ON assets (certificate_id) WHERE is_public_current AND role = 'public_derivative';

-- OCR / EXIF / PDF extraction results. Sensitive values are encrypted by the
-- application; raw metadata never gets copied to the public read model.
CREATE TABLE asset_extractions (
  extraction_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id uuid NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
  extractor_name text NOT NULL,
  extractor_version text,
  extracted_at timestamptz NOT NULL DEFAULT now(),
  confidence numeric(5,4),
  encrypted_metadata text NOT NULL,
  redacted_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  detected_credential_number_hash bytea,
  pii_field_names text[] NOT NULL DEFAULT '{}',
  processing_error text
);

CREATE INDEX asset_extractions_asset_idx ON asset_extractions (asset_id, extracted_at DESC);
CREATE INDEX asset_extractions_number_hash_idx
  ON asset_extractions (detected_credential_number_hash);

-- -------------------------------------------------------------------
-- External verification: reachability is not equivalent to authenticity
-- -------------------------------------------------------------------
CREATE TABLE verification_sources (
  verification_source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  source_kind text NOT NULL CHECK (
    source_kind IN ('issuer_registry', 'official_award_list', 'authority_api', 'manual_official_document')
  ),
  url text,
  authority_scope text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz
);

CREATE TABLE verification_checks (
  verification_check_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  verification_source_id uuid NOT NULL
    REFERENCES verification_sources(verification_source_id) ON DELETE CASCADE,
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  checked_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  http_status integer,
  http_reachable boolean NOT NULL,
  result evidence_state NOT NULL,
  matched_fields text[] NOT NULL DEFAULT '{}',
  mismatch_fields text[] NOT NULL DEFAULT '{}',
  error_code text,
  evidence_snapshot_asset_id uuid REFERENCES assets(asset_id),
  inspector_note text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX verification_checks_certificate_time
  ON verification_checks (certificate_id, checked_at DESC);

-- -------------------------------------------------------------------
-- Downstream projections
-- -------------------------------------------------------------------
CREATE TABLE certificate_read_models (
  certificate_id uuid PRIMARY KEY REFERENCES certificates(certificate_id) ON DELETE CASCADE,
  lifecycle_state certificate_lifecycle_state NOT NULL,
  evidence_state evidence_state NOT NULL,
  current_public_asset_id uuid REFERENCES assets(asset_id),
  current_verification_check_id uuid REFERENCES verification_checks(verification_check_id),
  state_computed_at timestamptz NOT NULL DEFAULT now(),
  server_clock_source text NOT NULL DEFAULT 'database_now',
  applied_event_id uuid REFERENCES certificate_events(event_id),
  version bigint NOT NULL,
  public_payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE skill_evidence_links (
  skill_evidence_link_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  skill_id uuid NOT NULL,
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id),
  is_currently_usable boolean NOT NULL DEFAULT true,
  usable_from timestamptz NOT NULL,
  usable_to timestamptz,
  removed_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (skill_id, certificate_id, usable_from)
);

CREATE TABLE resume_snapshots (
  resume_snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  resume_id uuid NOT NULL,
  version bigint NOT NULL,
  status text NOT NULL CHECK (status IN ('draft_candidate', 'frozen', 'delivered', 'archived')),
  snapshot jsonb NOT NULL,
  frozen_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (resume_id, version)
);

-- Frozen snapshots remain immutable. A post-freeze warning can be attached,
-- but the JSON snapshot itself is never rewritten.
CREATE TABLE resume_snapshot_warnings (
  warning_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  resume_snapshot_id uuid NOT NULL REFERENCES resume_snapshots(resume_snapshot_id),
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id),
  warning_type text NOT NULL,
  message text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    warning_type IN ('later_expired', 'later_revoked', 'source_became_stale', 'clock_corrected')
  )
);

CREATE TABLE resume_candidate_certificates (
  resume_id uuid NOT NULL,
  certificate_id uuid NOT NULL REFERENCES certificates(certificate_id),
  is_selected boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (resume_id, certificate_id)
);

-- -------------------------------------------------------------------
-- Outbox and clock audit
-- -------------------------------------------------------------------
CREATE TABLE outbox_events (
  outbox_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  aggregate_type text NOT NULL DEFAULT 'certificate',
  aggregate_id uuid NOT NULL,
  event_id uuid NOT NULL REFERENCES certificate_events(event_id),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  UNIQUE (event_id)
);

CREATE INDEX outbox_unprocessed_idx
  ON outbox_events (created_at)
  WHERE processed_at IS NULL;

CREATE TABLE server_clock_corrections (
  clock_correction_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  observed_at timestamptz NOT NULL,
  authoritative_at timestamptz NOT NULL,
  offset_seconds numeric NOT NULL,
  source text NOT NULL,
  affected_projections_rebuilt_at timestamptz,
  notes text
);

-- -------------------------------------------------------------------
-- Authoritative state calculation at a caller-supplied authoritative now.
-- It deliberately does not trust a cached state around expiry/revocation.
-- -------------------------------------------------------------------
CREATE OR REPLACE FUNCTION calculate_certificate_lifecycle(
  p_certificate_id uuid,
  p_now timestamptz
)
RETURNS certificate_lifecycle_state
LANGUAGE sql
STABLE
AS $$
  WITH latest_revocation AS (
    SELECT e.effective_at
    FROM certificate_events e
    WHERE e.certificate_id = p_certificate_id
      AND e.event_type = 'certificate.revoked'
      AND e.effective_at <= p_now
    ORDER BY e.effective_at DESC, e.sequence_no DESC
    LIMIT 1
  ),
  later_reinstatement AS (
    SELECT 1
    FROM certificate_events e
    JOIN latest_revocation r ON e.effective_at > r.effective_at
    WHERE e.certificate_id = p_certificate_id
      AND e.event_type = 'certificate.reinstated'
      AND e.effective_at <= p_now
    LIMIT 1
  ),
  award AS (
    SELECT effective_at
    FROM certificate_events
    WHERE certificate_id = p_certificate_id
      AND event_type = 'award.created'
    ORDER BY effective_at ASC, sequence_no ASC
    LIMIT 1
  ),
  active_interval AS (
    SELECT 1
    FROM certificate_validity_periods p, award a
    WHERE p.certificate_id = p_certificate_id
      AND p.valid_from <= p_now
      AND p.valid_to > p_now
      AND a.effective_at <= p_now
    LIMIT 1
  ),
  last_period AS (
    SELECT max(valid_to) AS valid_to
    FROM certificate_validity_periods
    WHERE certificate_id = p_certificate_id
  )
  SELECT CASE
    WHEN EXISTS (SELECT 1 FROM latest_revocation)
         AND NOT EXISTS (SELECT 1 FROM later_reinstatement)
      THEN 'revoked'::certificate_lifecycle_state
    WHEN NOT EXISTS (SELECT 1 FROM award)
         OR (SELECT effective_at FROM award) > p_now
      THEN 'not_active'::certificate_lifecycle_state
    WHEN EXISTS (SELECT 1 FROM active_interval)
      THEN 'valid'::certificate_lifecycle_state
    WHEN p_now >= COALESCE((SELECT valid_to FROM last_period), p_now)
      THEN 'expired'::certificate_lifecycle_state
    ELSE 'not_active'::certificate_lifecycle_state
  END;
$$;
