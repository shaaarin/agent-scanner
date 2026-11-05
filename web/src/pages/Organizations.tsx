import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { InviteRecord, MemberRecord, OrgRole, OrganizationRecord } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const ROLE_LABELS: Record<OrgRole, string> = {
  admin: "Администратор",
  editor: "Редактор",
  reader: "Наблюдатель",
};

export function Organizations() {
  const {user, refresh} = useAuth();
  const [orgs, setOrgs] = useState<OrganizationRecord[]>([]);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [createError, setCreateError] = useState("");
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setOrgs(await api.get<OrganizationRecord[]>("/orgs"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createOrg = async () => {
    setCreateError("");
    if (!newName.trim()) {
      setCreateError("Введите название организации");
      return;
    }
    try {
      await api.post<OrganizationRecord>("/orgs", {name: newName.trim(), description: newDescription.trim() || null});
      setCreating(false);
      setNewName("");
      setNewDescription("");
      // Новая организация появляется и в переключателе шапки.
      await refresh();
      await load();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e));
    }
  };

  const superadmin = user?.is_superadmin ?? false;

  return (
    <div>
      <PageHeader
        title="Организации"
        description="Владельцы активов, моделей и сканирований. Доступ выдаётся участникам организации: администратор управляет участниками, редактор создаёт и меняет активы, наблюдатель только читает."
        actions={
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Создать организацию
          </button>
        }
      />

      {error && <p role="alert" style={{color: "var(--danger, #b42318)"}}>{error}</p>}

      {creating && (
        <div className="card" style={{marginBottom: "1.6rem", display: "grid", gap: "0.8rem"}}>
          <h3 style={{margin: 0}}>Новая организация</h3>
          <label>
            Название
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Например: Лаборатория 2303" />
          </label>
          <label>
            Описание
            <input value={newDescription} onChange={(e) => setNewDescription(e.target.value)} placeholder="Для чего организация (необязательно)" />
          </label>
          {createError && <p role="alert" style={{margin: 0, color: "var(--danger, #b42318)"}}>{createError}</p>}
          <div style={{display: "flex", gap: "0.8rem"}}>
            <button className="btn btn-primary" onClick={createOrg}>Создать</button>
            <button className="btn btn-secondary" onClick={() => setCreating(false)}>Отмена</button>
          </div>
        </div>
      )}

      <div style={{display: "grid", gap: "1.2rem"}}>
        {orgs.map((org) => {
          const role = org.my_role;
          // Права на конкретную организацию определяет роль в ней
          // (системный админ может всё во всех).
          const orgAdmin = superadmin || role === "admin";
          const selected = selectedOrgId === org.id;
          return (
            <div key={org.id} className="card" style={{padding: "1.6rem"}}>
              <div style={{display: "flex", alignItems: "center", gap: "1.2rem", flexWrap: "wrap"}}>
                <div style={{flex: 1, minWidth: "16rem"}}>
                  <strong style={{fontSize: "1.7rem"}}>{org.name}</strong>
                  {org.description && (
                    <div style={{color: "var(--text-500)", marginTop: "0.3rem"}}>{org.description}</div>
                  )}
                </div>
                <span className="badge">{ROLE_LABELS[role ?? "reader"]}</span>
                <span style={{color: "var(--text-500)"}}>Участников: {org.members_count}</span>
                <button className="btn btn-secondary btn-sm" onClick={() => setSelectedOrgId(selected ? null : org.id)}>
                  {selected ? "Скрыть участников" : "Участники"}
                </button>
              </div>
              {selected && <OrgMembers orgId={org.id} isAdmin={orgAdmin} onChanged={load} />}
            </div>
          );
        })}
        {orgs.length === 0 && !error && (
          <p style={{color: "var(--text-500)"}}>
            Пока нет ни одной организации. Создайте её -- активы, LLM-модели и сканирования
            хранятся внутри организаций.
          </p>
        )}
      </div>
    </div>
  );
}

function OrgMembers({orgId, isAdmin, onChanged}: {orgId: number; isAdmin: boolean; onChanged: () => void}) {
  const [members, setMembers] = useState<MemberRecord[]>([]);
  const [invites, setInvites] = useState<InviteRecord[]>([]);
  const [error, setError] = useState("");
  const [inviteRole, setInviteRole] = useState<OrgRole>("reader");
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setMembers(await api.get<MemberRecord[]>(`/orgs/${orgId}/members`));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [orgId]);

  const loadInvites = useCallback(async () => {
    if (!isAdmin) return;
    try {
      setInvites(await api.get<InviteRecord[]>(`/orgs/${orgId}/invites`));
    } catch {
      // Список ссылок -- вспомогательный блок, молча переживаем.
    }
  }, [orgId, isAdmin]);

  useEffect(() => {
    void load();
    void loadInvites();
  }, [load, loadInvites]);

  const createInvite = async () => {
    setError("");
    try {
      await api.post(`/orgs/${orgId}/invites`, {role: inviteRole});
      await loadInvites();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const copyLink = async (invite: InviteRecord) => {
    const url = `${window.location.origin}/invite/${invite.token}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopiedId(invite.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      window.prompt("Скопируйте ссылку вручную:", url);
    }
  };

  const revokeInvite = async (inviteId: number) => {
    setError("");
    try {
      await api.delete(`/orgs/${orgId}/invites/${inviteId}`);
      await loadInvites();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const changeRole = async (userId: number, newRole: OrgRole) => {
    setError("");
    try {
      await api.patch(`/orgs/${orgId}/members/${userId}`, {role: newRole});
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const removeMember = async (userId: number) => {
    setError("");
    try {
      await api.delete(`/orgs/${orgId}/members/${userId}`);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div style={{marginTop: "1.6rem", borderTop: "0.1rem solid var(--separator-default)", paddingTop: "1.2rem"}}>
      {error && <p role="alert" style={{color: "var(--danger, #b42318)"}}>{error}</p>}
      <table style={{width: "100%", borderCollapse: "collapse"}}>
        <thead>
          <tr style={{textAlign: "left", color: "var(--text-500)"}}>
            <th style={{padding: "0.6rem"}}>Логин</th>
            <th style={{padding: "0.6rem"}}>Имя</th>
            <th style={{padding: "0.6rem"}}>E-mail</th>
            <th style={{padding: "0.6rem"}}>Последний вход</th>
            <th style={{padding: "0.6rem"}}>Роль</th>
            {isAdmin && <th style={{padding: "0.6rem"}}></th>}
          </tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.user_id} style={{borderTop: "0.1rem solid var(--separator-default)"}}>
              <td style={{padding: "0.6rem"}}>
                {member.login}
                {member.is_superadmin && <span className="badge" style={{marginLeft: "0.6rem"}}>Системный администратор</span>}
                {!member.last_login_at && (
                  <span style={{color: "var(--text-500)", marginLeft: "0.6rem"}}>(ещё не входил)</span>
                )}
              </td>
              <td style={{padding: "0.6rem"}}>{member.display_name ?? "—"}</td>
              <td style={{padding: "0.6rem"}}>{member.email ?? "—"}</td>
              <td style={{padding: "0.6rem"}}>
                {member.last_login_at ? new Date(member.last_login_at).toLocaleString("ru-RU") : "—"}
              </td>
              <td style={{padding: "0.6rem"}}>
                {isAdmin ? (
                  <select value={member.role} onChange={(e) => changeRole(member.user_id, e.target.value as OrgRole)}>
                    <option value="admin">Администратор</option>
                    <option value="editor">Редактор</option>
                    <option value="reader">Наблюдатель</option>
                  </select>
                ) : (
                  ROLE_LABELS[member.role]
                )}
              </td>
              {isAdmin && (
                <td style={{padding: "0.6rem", textAlign: "right"}}>
                  <button className="btn btn-danger btn-sm" onClick={() => removeMember(member.user_id)}>
                    Исключить
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {isAdmin && (
        <div style={{marginTop: "1.6rem"}}>
          <div style={{display: "flex", gap: "0.8rem", alignItems: "end", flexWrap: "wrap"}}>
            <label>
              Роль по ссылке
              <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value as OrgRole)}>
                <option value="admin">Администратор</option>
                <option value="editor">Редактор</option>
                <option value="reader">Наблюдатель</option>
              </select>
            </label>
            <button className="btn btn-primary" onClick={createInvite}>Создать ссылку-приглашение</button>
          </div>
          {invites.filter((invite) => !invite.used).map((invite) => (
            <div key={invite.id} style={{display: "flex", gap: "0.8rem", marginTop: "0.8rem", alignItems: "center", flexWrap: "wrap"}}>
              <input
                readOnly
                value={`${window.location.origin}/invite/${invite.token}`}
                style={{flex: 1, minWidth: "16rem", fontFamily: "ui-monospace, monospace", fontSize: "0.85rem"}}
                onFocus={(e) => e.currentTarget.select()}
              />
              <button className="btn btn-secondary btn-sm" onClick={() => copyLink(invite)}>
                {copiedId === invite.id ? "Скопировано" : "Копировать"}
              </button>
              <button className="btn btn-danger btn-sm" onClick={() => revokeInvite(invite.id)} title="Ссылка перестанет работать">
                Отозвать
              </button>
              <span style={{color: "var(--text-500)", fontSize: "0.85rem"}}>{ROLE_LABELS[invite.role]}</span>
            </div>
          ))}
          <p style={{color: "var(--text-500)", marginTop: "0.8rem"}}>
            Передайте ссылку приглашаемому: после входа он увидит кнопку «Принять приглашение»
            и получит роль из ссылки. Ссылка одноразовая; созданную по ошибке можно отозвать.
          </p>
        </div>
      )}
    </div>
  );
}
