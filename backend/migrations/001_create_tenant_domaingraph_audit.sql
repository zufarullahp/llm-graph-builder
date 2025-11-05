-- Migration: create Tenant, DomainGraph and DomainProvisionAudit tables

-- Tenant table (used by backend)
CREATE TABLE IF NOT EXISTS "Tenant" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "name" text NOT NULL,
  "ownerUserId" uuid NOT NULL,
  "ownerEmail" text,
  "plan" text NOT NULL DEFAULT 'STANDARD',
  "isActive" boolean NOT NULL DEFAULT true,
  "createdAt" timestamptz NOT NULL DEFAULT now(),
  "updatedAt" timestamptz NOT NULL DEFAULT now()
);

-- DomainGraph table (backend provisioning registry / credentials)
CREATE TABLE IF NOT EXISTS "DomainGraph" (
  "domainId" uuid PRIMARY KEY,
  "provisionStatus" text NOT NULL DEFAULT 'provisioning',
  "seedStatus" text NOT NULL DEFAULT 'not_started',
  "idempotencyKey" text,
  "credVersion" integer NOT NULL DEFAULT 1,
  "neo4jUri" text,
  "neo4jDatabase" text,
  "neo4jUsername" text,
  "neo4jSecretEnc" text,
  "provisionedAt" timestamptz,
  "failReason" text,
  "createdAt" timestamptz NOT NULL DEFAULT now(),
  "updatedAt" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_domain
    FOREIGN KEY ("domainId")
    REFERENCES "Domain" ("id")
    ON DELETE CASCADE
);

-- Audit table for provisioning attempts
CREATE TABLE IF NOT EXISTS "DomainProvisionAudit" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "domainId" uuid NOT NULL,
  "event" text NOT NULL,
  "actor" text,
  "result" text,
  "payload" jsonb,
  "createdAt" timestamptz NOT NULL DEFAULT now()
);
