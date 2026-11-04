-- =====================================================================
-- Enterprise Intelligence Platform - Database Schema & DDL
-- Compatible with PostgreSQL 14+ and SQLite 3
-- Generated from SQLAlchemy Models (app/models.py)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. USERS TABLE
-- Stores user authentication credentials and account metadata.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);


-- ---------------------------------------------------------------------
-- 2. DOCUMENTS TABLE
-- Stores metadata, processing state, and SHA-256 deduplication hashes.
-- Duplicate uploads by the same user are rejected at DB level via uq_user_filehash.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL,            -- 'pdf', 'txt', 'md', 'csv'
    file_hash VARCHAR(64) NOT NULL,            -- SHA-256 checksum
    size_bytes INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL, -- 'pending', 'processing', 'ready', 'failed'
    error TEXT,
    chunk_count INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_user_filehash UNIQUE (user_id, file_hash)
);

CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS ix_documents_status ON documents(status);


-- ---------------------------------------------------------------------
-- 3. CONVERSATIONS TABLE
-- Tracks multi-session chat history per user with context summaries.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) DEFAULT 'New chat' NOT NULL,
    summary TEXT,
    summary_upto INTEGER DEFAULT 0 NOT NULL,   -- Last message ID folded into summary
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations(user_id);


-- ---------------------------------------------------------------------
-- 4. MESSAGES TABLE
-- Individual conversational turns, cited sources, and agent reasoning traces.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,                 -- 'user' | 'assistant'
    content TEXT NOT NULL,
    sources JSON,                              -- Array of retrieved chunk citations
    agent_steps JSON,                          -- Sequential LangGraph tool execution logs
    meta JSON,                                 -- Latency, token usage, verification scores, conflicts
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages(conversation_id);


-- ---------------------------------------------------------------------
-- 5. LLM_LOGS TABLE
-- Audit log of every LLM invocation for cost, latency, and fallback tracking.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind VARCHAR(30) NOT NULL,                 -- 'chat', 'rewrite', 'verify', 'agent', 'summary'
    model VARCHAR(80) NOT NULL,                -- e.g. 'gemini-2.5-flash', 'gemini-1.5-flash'
    prompt_tokens INTEGER DEFAULT 0 NOT NULL,
    completion_tokens INTEGER DEFAULT 0 NOT NULL,
    latency_ms INTEGER DEFAULT 0 NOT NULL,
    success BOOLEAN DEFAULT TRUE NOT NULL,
    cached BOOLEAN DEFAULT FALSE NOT NULL,
    fallback_used BOOLEAN DEFAULT FALSE NOT NULL,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_llm_logs_user_id ON llm_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_llm_logs_created_at ON llm_logs(created_at);


-- ---------------------------------------------------------------------
-- 6. ACTIVITY_LOGS TABLE
-- Application-level audit trail (uploads, deletes, logins, errors).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(50) NOT NULL,               -- 'document_upload', 'login', 'document_delete'
    detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_activity_logs_user_id ON activity_logs(user_id);


-- =====================================================================
-- 7. VECTOR DATABASE SCHEMA (WEAVIATE CLOUD / DocChunk COLLECTION)
-- =====================================================================
-- Class / Collection Name: DocChunk
-- Vectorizer: None (self-provided dense embeddings from all-MiniLM-L6-v2)
-- Dimensions: 384
-- Distance Metric: Cosine
--
-- Properties:
--   - user_id       (DataType: INT, Filterable: true, Searchable: false)
--   - document_id   (DataType: INT, Filterable: true, Searchable: false)
--   - filename      (DataType: TEXT, Filterable: true, Searchable: true)
--   - chunk_index   (DataType: INT, Filterable: true, Searchable: false)
--   - page          (DataType: INT, Filterable: true, Searchable: false)
--   - content       (DataType: TEXT, Filterable: true, Searchable: true, Tokenization: word)
-- =====================================================================

