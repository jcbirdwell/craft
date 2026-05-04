
from birdwell.database import CoreDatabase
import logging

log = logging.getLogger(__name__)



class ModpackDB(CoreDatabase):
    def set_project(self, project: dict):
        # language=sql
        q = """
            insert into projects (project_name, project_type, project_env, mr_pid, cs_pid, cs_project_raw, mr_project_raw)
            select project_name, project_type, project_env, mr_pid, cs_pid, cs_project_raw, mr_project_raw
            from jsonb_to_record(%s::jsonb) as j(
                                                 project_name varchar,
                                                 project_type project_type,
                                                 project_env project_env,
                                                 mr_pid varchar,
                                                 cs_pid varchar,
                                                 cs_project_raw jsonb,
                                                 mr_project_raw jsonb
                )
            returning projects.* \
            """
        return self.query2(q, self.ec(project), single=True)

    def set_release(self, release: dict):
        # language=sql
        q = """
            with ins as (
                INSERT INTO project_releases (
                                              pid,
                                              mr_vid,
                                              mr_rid,
                                              cs_rid,
                                              mc_versions,
                                              loaders,
                                              dependencies,
                                              release_version,
                                              release_type,
                                              sha1,
                                              sha256,
                                              sha512,
                                              md5,
                                              murmur2,
                                              mr_url,
                                              cs_url,
                                              file_size_bytes,
                                              file_path,
                                              cs_match_raw,
                                              mr_match_raw,
                                              filename,
                                              release_ts
                    )
                    SELECT
                        j.pid,
                        j.mr_vid,
                        j.mr_rid,
                        j.cs_rid,
                        j.mc_versions,
                        j.loaders,
                        j.dependencies,
                        j.release_version,
                        j.release_type,
                        j.sha1,
                        j.sha256,
                        j.sha512,
                        j.md5,
                        j.murmur2,
                        j.mr_url,
                        j.cs_url,
                        j.file_size_bytes,
                        j.file_path,
                        j.cs_match_raw,
                        j.mr_match_raw,
                        j.filename,
                        j.release_ts
                    FROM jsonb_to_record(%s)
                             AS j(
                                  pid bigint,
                                  mr_vid varchar,
                                  mr_rid varchar,
                                  cs_rid varchar,
                                  mc_versions varchar[],
                                  loaders varchar[],
                                  dependencies bigint[],
                                  release_version varchar,
                                  release_type release_type,
                                  sha1 varchar,
                                  sha256 varchar,
                                  sha512 varchar,
                                  md5 varchar,
                                  murmur2 bigint,
                                  mr_url varchar,
                                  cs_url varchar,
                                  file_size_bytes bigint,
                                  file_path varchar,
                                  cs_match_raw jsonb,
                                  mr_match_raw jsonb,
                                  filename varchar,
                                  release_ts timestamptz
                            )
                    ON CONFLICT (sha1)
                        DO UPDATE SET
                            pid =     COALESCE(excluded.pid, 	    project_releases.pid),
                            mr_vid =  COALESCE(excluded.mr_vid, 	project_releases.mr_vid),
                            mr_rid =  COALESCE(excluded.mr_rid, 	project_releases.mr_rid),
                            cs_rid =  COALESCE(excluded.cs_rid, 	project_releases.cs_rid),
                            mc_versions =       COALESCE(excluded.mc_versions, 	    project_releases.mc_versions),
                            loaders =           COALESCE(excluded.loaders, 	        project_releases.loaders),
                            dependencies =      COALESCE(excluded.dependencies, 	project_releases.dependencies),
                            release_version =   COALESCE(excluded.release_version, 	project_releases.release_version),
                            release_type =      COALESCE(excluded.release_type, 	project_releases.release_type),
                            sha256 =  COALESCE(excluded.sha256, 	project_releases.sha256),
                            sha512 =  COALESCE(excluded.sha512, 	project_releases.sha512),
                            md5 =     COALESCE(excluded.md5, 	    project_releases.md5),
                            murmur2 = COALESCE(excluded.murmur2, 	project_releases.murmur2),
                            mr_url =  COALESCE(excluded.mr_url, 	project_releases.mr_url),
                            cs_url =  COALESCE(excluded.cs_url, 	project_releases.cs_url),
                            file_size_bytes = COALESCE(excluded.file_size_bytes, 	project_releases.file_size_bytes),
                            file_path =       COALESCE(excluded.file_path, 	        project_releases.file_path),
                            cs_match_raw =    COALESCE(excluded.cs_match_raw, 	    project_releases.cs_match_raw),
                            mr_match_raw =    COALESCE(excluded.mr_match_raw, 	    project_releases.mr_match_raw),
                            filename =        COALESCE(excluded.filename,           project_releases.filename),
                            release_ts =      COALESCE(excluded.release_ts,         project_releases.release_ts)
                    returning project_releases.*
            )
            select *
            from ins
                     left join projects using (pid) \
            """
        return self.query2(q, self.ec(release), single=True)

    def update_project_file_fields(self, rid, pack: dict):
        # language=sql
        q = """
            with ups as (
                update project_releases
                    set
                        sha1    = COALESCE(j.sha1,      project_releases.sha1),
                        sha256  = COALESCE(j.sha256, 	project_releases.sha256),
                        sha512  = COALESCE(j.sha512, 	project_releases.sha512),
                        md5     = COALESCE(j.md5, 	    project_releases.md5),
                        murmur2 = COALESCE(j.murmur2, 	project_releases.murmur2),
                        file_size_bytes = COALESCE(j.file_size_bytes, 	project_releases.file_size_bytes),
                        file_path       = COALESCE(j.file_path, 	    project_releases.file_path)
                    from jsonb_to_record(%(pack)s::jsonb)
                        as j
                        (
                         sha1 varchar,
                         sha256 varchar,
                         sha512 varchar,
                         md5 varchar,
                         murmur2 bigint,
                         file_size_bytes bigint,
                         file_path varchar
                            )
                    where %(rid)s::bigint = project_releases.rid
                    returning project_releases.*)
            select *
            from ups
                     left join projects using (pid) \
            """
        return self.query2(q, {'pack': self.ec(pack), 'rid': rid}, single=True)


    def get_curse_project(self, curse_pid: int):
        # language=sql
        q = """
            select *
            from projects
            where cs_pid = %s::varchar \
            """
        return self.query(q, (curse_pid,), single=True)

    def get_rinth_project(self, modrinth_pid: str):
        # language=sql
        q = """
            select *
            from projects
            where mr_pid = %s::varchar
            """
        return self.query2(q, modrinth_pid, single=True)

    def get_release_sha1(self, sha1_hex: str) -> dict | None:
        # language=sql
        q = """
            select *
            from project_releases
                     left join projects using (pid)
            where sha1 = %s::varchar \
            """
        return self.query(q, (sha1_hex,), single=True)

    def modrinth_missing(self):
        # language=sql
        q = """
            select *
            from projects
            where mr_pid is null
              and platform_exclusive is null \
            """

        return self.query2(q)

    def set_project_exclusive(self, pid, platforms):
        # language=sql
        q = """
            update projects
            set platform_exclusive = %s::distribution_platform[]
            where pid = %s::bigint \
            """
        return self.query2(q, platforms, pid)


    def update_project(self, project_id: int, pack: dict):
        # language=sql
        q = """
            update projects p
            set
                project_name  = coalesce(j.project_name,  p.project_name),
                project_type  = coalesce(j.project_type,  p.project_type),
                project_env   = coalesce(j.project_env,   p.project_env),
                mr_pid  = coalesce(j.mr_pid,  p.mr_pid),
                cs_pid     = coalesce(j.cs_pid,     p.cs_pid),
                mr_project_raw = coalesce(j.mr_project_raw, p.mr_project_raw),
                cs_project_raw    = coalesce(j.cs_project_raw,    p.cs_project_raw)
            from
                jsonb_to_record(%(data)s::jsonb) as j(
                                                      project_name varchar,
                                                      project_type project_type,
                                                      project_env project_env,
                                                      mr_pid varchar,
                                                      cs_pid varchar,
                                                      mr_project_raw jsonb,
                                                      cs_project_raw jsonb
                    )
            where p.pid = %(pid)s
            returning p.* \
            """
        return self.query2(q, {'pid': project_id, 'data': self.ec(pack)}, single=True)

    def project_merge_releases(self, old_pid, fresh_pid):
        # language=sql
        q = """
            with transfer as
                     (
                         update project_releases
                             set pid = %(fresh)s::bigint
                             where pid = %(old)s::bigint
                     )

            update project_releases pr
            set dependencies =
                    (
                        select array_agg(distinct other_dep) || %(fresh)s::bigint
                        from project_releases pr2, unnest(pr2.dependencies) as other_dep
                        where pr2.pid = pr.pid
                          and other_dep != %(old)s::bigint -- drop old
                          and other_dep != %(fresh)s::bigint -- prevent duplicate
                    )
            where %(old)s::bigint = any(dependencies) \
            """
        return self.query2(q, {'fresh': fresh_pid, 'old': old_pid})

    def merge_projects(self, old_pid: int, fresh_pid: int, updates: dict = None):
        """update releases to reference new pid and update target (fresh) project with given updates"""
        # language=sql
        q = """
            with transfer as
                     (
                         update project_releases
                             set pid = %(fresh)s::bigint
                             where pid = %(old)s::bigint
                     ),
                 dep_tranfer as
                     (
                         update project_releases pr
                             set dependencies = (
                                 select array_agg(distinct other_dep) || %(fresh)s::bigint
                                 from project_releases pr2, unnest(pr2.dependencies) as other_dep
                                 where pr2.pid = pr.pid
                                   and other_dep != %(old)s::bigint -- drop old
                                   and other_dep != %(fresh)s::bigint -- prevent duplicate
                             )
                             where %(old)s::bigint = any(dependencies)
                     ),
                 -- need to remove old project before we update the new one with platform _pid or they will collide
                 rem as
                     (
                         delete from projects where pid = %(old)s::bigint
                     ),
                 ups as
                     (
                         update projects p
                             set
                                 project_name   = coalesce(j.project_name,   p.project_name),
                                 project_type   = coalesce(j.project_type,   p.project_type),
                                 project_env    = coalesce(j.project_env,    p.project_env),
                                 mr_pid         = coalesce(j.mr_pid,         p.mr_pid),
                                 cs_pid         = coalesce(j.cs_pid,         p.cs_pid),
                                 mr_project_raw = coalesce(j.mr_project_raw, p.mr_project_raw),
                                 cs_project_raw = coalesce(j.cs_project_raw, p.cs_project_raw)
                             from
                                 jsonb_to_record(%(data)s::jsonb)
                                     as j(
                                          project_name    varchar,
                                          project_type    project_type,
                                          project_env     project_env,
                                          mr_pid          varchar,
                                          cs_pid          varchar,
                                          mr_project_raw  jsonb,
                                          cs_project_raw  jsonb
                                     )
                             where p.pid = %(fresh)s::bigint
                             returning p.*
                     )

            select *
            from ups \
            """
        return self.query2(q, {'fresh': fresh_pid, 'old': old_pid, 'data': self.ec(updates)}, single=True)

    def releases(self, pid: int = None, loader='neoforge', mc_version='1.21.1'):
        # language=sql
        q = """
            select *
            from project_releases
                     join projects using (pid)

            where (%(pid)s::bigint is null or pid = %(pid)s::bigint)
              and (%(loader)s::varchar is null or %(loader)s::varchar = any(loaders))
              and (%(mc_version)s::varchar is null or %(mc_version)s::varchar = any(mc_versions))
            order by release_ts desc \
            """
        return self.query2(q, {'pid': pid, 'loader': loader, 'mc_version': mc_version})

    def latest_release(self, pid, loader=None, mc_version=None):
        # language=sql
        q = """
            select *
            from project_releases
                     join projects using (pid)

            where pid = %(pid)s::bigint
              and (%(loader)s::varchar is null or %(loader)s::varchar = any(loaders))
              and (%(mc_version)s::varchar is null or %(mc_version)s::varchar = any(mc_versions))
            order by release_ts desc
            limit 1
            """
        return self.query2(q, {'pid': pid, 'loader': loader, 'mc_version': mc_version}, single=True)

    def project(self, pid):
        # language=sql
        q = """
            select *
            from projects
            where pid = %s::bigint \
            """
        return self.query2(q, pid, single=True)

    def set_modlist(self, mid, entries: list[tuple], clear=False):
        # language=sql
        q = """
            with pre as (
                delete from modlist where %(clear)s::bool and mid = %(mid)s::bigint
            )
            insert into modlist (mid, rid, note)
            select %(mid)s::bigint, rid, note
            from unnest(%(entries)s::modpack_entry[])
            on conflict (mid, rid)
                do update set note = coalesce(excluded.note, modlist.note); \
            """
        return self.query2(q, {'mid': mid, 'clear': clear, 'entries': entries})

    def set_modpack(self, name: str, version: str, mods: list[tuple | int | list], change_log: dict = None):
        fixed_entry = []
        for x in mods:
            if isinstance(x, int):
                fixed_entry.append((x, None))
            elif isinstance(x, str):
                fixed_entry.append((int(x), None))
            elif isinstance(x, (list, tuple)):
                if len(x) == 2:
                    fixed_entry.append(tuple(x))
                elif len(x) == 1:
                    fixed_entry.append((x[0], None))
                else:
                    raise ValueError(f'bad mod content "{x}"')
            else:
                raise ValueError(f'bad mod content "{x}"')

        # language=sql
        q = """
            with base as
                     (
                         insert into modpack (pack_name, pack_version, change_log)
                             select %s::varchar, %s::varchar, %s::jsonb
                             returning mid
                     ),
                 mods as
                     (
                         insert into modlist (mid, rid, note)
                             select mid, rid, note
                             from base, unnest(%s::modpack_entry[])
                     )
            select mid from base \
            """
        return self.query2(q, name, version, self.ec(change_log), fixed_entry, single=0)

    def swap_mods(self, mid, swaps: list):
        full_swaps = []
        for x in swaps:
            if len(x) == 3:
                full_swaps.append(tuple(x))
            elif len(x) == 2:
                full_swaps.append(tuple((*x, None)))
            else:
                raise ValueError(f'bad swap {x}')

        # language=sql
        q = """
            update modlist
            set rid = u.fresh_rid,
                note = coalesce(u.note, note)
            from
                (
                    select %(mid)s::bigint as mid, cur_rid, fresh_rid, note
                    from unnest(%(swaps)s::modpack_swap[])
                ) u
            where modlist.mid = %(mid)s::bigint and modlist.rid = u.cur_rid \
            """

        return self.query2(q, {'mid': mid, 'swaps': full_swaps})

    def lock_modpack(self, mid: int):
        """this locks the contents of a modpack version from being edited... for finalizing a pack for export"""
        # language=sql
        q = """
            update modpack
            set mod_count = ( select count(*) from modlist where mid = %(mid)s::bigint)
            where mid = %(mid)s::bigint \
            """
        return self.query2(q, {'mid': mid})

    def bump_release_fetch(self, project_id):
        # language=sql
        q = """
            update projects
            set release_fetch_ts = current_timestamp
            where pid = %s::bigint
            returning release_fetch_ts \
            """
        return self.query2(q, project_id, single=0)

    def _fix_releases(self):
        rels = self.releases()
        result = []
        for x in rels:
            if x['release_ts']: continue
            if x['mr_match_raw']:
                result.append([x['rid'], x['mr_match_raw']['date_published']])
            elif x['cs_match_raw']:
                if 'fileDate' in x['cs_match_raw']:
                    date = x['cs_match_raw']['fileDate']
                else:
                    date = x['cs_match_raw']['exactMatches'][0]['file']['fileDate']
                result.append([x['rid'], date])
            else:
                print(f'missed "{x['filename']}"')

        self.query2(
            'update project_releases '
            'set release_ts = u.val::timestamptz '
            'from unnest(%s::id_var_pair[]) u '
            'where u.id = rid',
            [tuple(x) for x in result]
        )

    def get_modpacks(self, names: list[str] = None, versions: list[str] = None):
        # language=sql
        q = """
            select
                mid,
                pack_name,
                pack_version,
                note,
                p.*,
                pj.*

            from modpack mp
                     left join modlist ml using (mid)
                     left join project_releases pj using (rid)
                     left join projects p using (pid)
            where
                ( %(pack_names)s::varchar is null or mp.pack_name = any(%(pack_names)s::varchar[]) )
              and ( %(pack_versions)s::varchar is null or mp.pack_version = any(%(pack_versions)s::varchar[]) )
            order by pack_name, pack_version desc, pj.pid \
            """
        return self.query2(q, { 'pack_names': names, 'pack_versions': versions })

