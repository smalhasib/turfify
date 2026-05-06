-- Enable btree_gist for the GIST exclusion constraint on booking_slots
-- (Required from Phase 1 onward; harmless to enable now.)
CREATE EXTENSION IF NOT EXISTS btree_gist;
