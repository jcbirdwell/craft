--
-- PostgreSQL database dump
--

\restrict 2RE16Sif5CjOQVvg6g7boDlDFNXBVdFyKYsXczV4JUqLnopWnkMXD6vQByPGm11

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: distribution_platform; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.distribution_platform AS ENUM (
    'curse',
    'modrinth'
);


ALTER TYPE public.distribution_platform OWNER TO postgres;

--
-- Name: id_var_pair; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.id_var_pair AS (
	id bigint,
	val character varying
);


ALTER TYPE public.id_var_pair OWNER TO postgres;

--
-- Name: mod_loader; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.mod_loader AS ENUM (
    'neoforge',
    'forge',
    'fabric',
    'quilt'
);


ALTER TYPE public.mod_loader OWNER TO postgres;

--
-- Name: modpack_entry; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.modpack_entry AS (
	rid bigint,
	note text
);


ALTER TYPE public.modpack_entry OWNER TO postgres;

--
-- Name: modpack_swap; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.modpack_swap AS (
	cur_rid bigint,
	fresh_rid bigint,
	note text
);


ALTER TYPE public.modpack_swap OWNER TO postgres;

--
-- Name: pack_slug; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.pack_slug AS (
	pack_name character varying,
	pack_version character varying
);


ALTER TYPE public.pack_slug OWNER TO postgres;

--
-- Name: project_env; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.project_env AS ENUM (
    'client_only',
    'server_only',
    'both',
    'unknown'
);


ALTER TYPE public.project_env OWNER TO postgres;

--
-- Name: project_type; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.project_type AS ENUM (
    'mod',
    'texture',
    'shader',
    'data',
    'file',
    'unknown'
);


ALTER TYPE public.project_type OWNER TO postgres;

--
-- Name: release_type; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.release_type AS ENUM (
    'release',
    'beta',
    'alpha'
);


ALTER TYPE public.release_type OWNER TO postgres;

--
-- Name: test_de; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.test_de AS ENUM (
    'test1',
    'value1'
);


ALTER TYPE public.test_de OWNER TO postgres;

--
-- Name: collect_and_validate_enum_values(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.collect_and_validate_enum_values() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    missing_enum text;
    required TEXT[];
BEGIN
    -- 2. collect all custom_status values from the statement
    SELECT array_agg(DISTINCT n.test_enum)
    INTO required
    FROM NEW n
    left join (
        SELECT enumlabel
        FROM pg_enum
        WHERE enumtypid = 'test_de'::regtype
    ) e on e.enumlabel = n.test_enum
    WHERE n.test_enum IS NOT NULL
      and e.enumlabel is null;

    -- 3. update enum with missing values
    FOREACH missing_enum IN ARRAY required LOOP

            EXECUTE format('ALTER TYPE test_de ADD VALUE %L', missing_enum);
    END LOOP;

    RETURN NULL;
END;
$$;


ALTER FUNCTION public.collect_and_validate_enum_values() OWNER TO postgres;

--
-- Name: prevent_finalized_modlist_modification(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.prevent_finalized_modlist_modification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        if (select (mod_count is not null) from modpack where mid = OLD.mid) then
            RAISE EXCEPTION 'cannot remove mod from a finalized modpack. create a new version to edit.';
        end if;
    -- 2. Block inserts when modpack has non-null mod_count
    ELSIF TG_OP = 'INSERT' THEN
        if (SELECT (mod_count IS NOT NULL) FROM modpack WHERE mid = NEW.mid) then
            RAISE EXCEPTION 'Cannot insert modlist for modpack with non-null mod_count';
        end if;
        -- 3. Block updates to rid when modpack has non-null mod_count
    ELSIF TG_OP = 'UPDATE' THEN
        if (NEW.rid <> OLD.rid AND (SELECT (mod_count IS NOT NULL) FROM modpack WHERE mid = NEW.mid)) then
            RAISE EXCEPTION 'Cannot update rid for modpack with non-null mod_count';
        end if;
    END IF;

    RETURN NEW;
END;
$$;


ALTER FUNCTION public.prevent_finalized_modlist_modification() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: modlist; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.modlist (
    mid bigint NOT NULL,
    rid bigint NOT NULL,
    note text
);


ALTER TABLE public.modlist OWNER TO postgres;

--
-- Name: modpack; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.modpack (
    mid integer NOT NULL,
    pack_name character varying NOT NULL,
    pack_version character varying NOT NULL,
    mod_count integer,
    change_log jsonb,
    creation_ts timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.modpack OWNER TO postgres;

--
-- Name: modpack_mid_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.modpack ALTER COLUMN mid ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.modpack_mid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: project_releases; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.project_releases (
    pid bigint NOT NULL,
    rid bigint NOT NULL,
    mr_vid character varying,
    mr_rid character varying,
    cs_rid character varying,
    mc_versions character varying[],
    loaders character varying[],
    dependencies bigint[],
    release_version character varying NOT NULL,
    release_type public.release_type NOT NULL,
    sha1 character varying,
    sha256 character varying,
    sha512 character varying,
    md5 character varying,
    murmur2 bigint,
    mr_url character varying,
    cs_url character varying,
    file_size_bytes bigint,
    file_path character varying,
    cs_match_raw jsonb,
    mr_match_raw jsonb,
    release_ts timestamp with time zone NOT NULL,
    filename character varying
);


ALTER TABLE public.project_releases OWNER TO postgres;

--
-- Name: project_releases_rid_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.project_releases ALTER COLUMN rid ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.project_releases_rid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: projects; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.projects (
    pid bigint NOT NULL,
    project_name character varying NOT NULL,
    project_type public.project_type NOT NULL,
    project_env public.project_env NOT NULL,
    mr_pid character varying,
    cs_pid character varying,
    ts timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    mr_project_raw jsonb,
    cs_project_raw jsonb,
    platform_exclusive public.distribution_platform[],
    release_fetch_ts timestamp with time zone
);


ALTER TABLE public.projects OWNER TO postgres;

--
-- Name: projects_pid_seq1; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.projects ALTER COLUMN pid ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.projects_pid_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: modlist modlist_mid_rid_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.modlist
    ADD CONSTRAINT modlist_mid_rid_pk PRIMARY KEY (mid, rid);


--
-- Name: modpack modpack_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.modpack
    ADD CONSTRAINT modpack_pkey PRIMARY KEY (mid);


--
-- Name: modpack pack_slug_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.modpack
    ADD CONSTRAINT pack_slug_pk UNIQUE (pack_name, pack_version);


--
-- Name: project_releases project_releases_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.project_releases
    ADD CONSTRAINT project_releases_pkey PRIMARY KEY (rid);


--
-- Name: project_releases project_releases_sha1_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.project_releases
    ADD CONSTRAINT project_releases_sha1_key UNIQUE (sha1);


--
-- Name: projects projects_cs_pid_uk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_cs_pid_uk UNIQUE (cs_pid) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: projects projects_mr_pid_uk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_mr_pid_uk UNIQUE (mr_pid) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: projects projects_pkey1; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey1 PRIMARY KEY (pid);


--
-- Name: modlist prevent_finalized_modlist_modification_trig; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER prevent_finalized_modlist_modification_trig BEFORE INSERT OR DELETE OR UPDATE ON public.modlist FOR EACH ROW EXECUTE FUNCTION public.prevent_finalized_modlist_modification();


--
-- Name: modlist modlist_mid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.modlist
    ADD CONSTRAINT modlist_mid_fkey FOREIGN KEY (mid) REFERENCES public.modpack(mid) ON UPDATE CASCADE;


--
-- Name: modlist modlist_rid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.modlist
    ADD CONSTRAINT modlist_rid_fkey FOREIGN KEY (rid) REFERENCES public.project_releases(rid) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: project_releases project_releases_pid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.project_releases
    ADD CONSTRAINT project_releases_pid_fkey FOREIGN KEY (pid) REFERENCES public.projects(pid) ON UPDATE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict 2RE16Sif5CjOQVvg6g7boDlDFNXBVdFyKYsXczV4JUqLnopWnkMXD6vQByPGm11

