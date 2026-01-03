/**
 * ProvisioningPanel - SCIM Provisioning Management (v4.4.0 PR9)
 *
 * Admin panel for managing:
 * - SCIM tokens (create, revoke, list)
 * - SCIM groups (view synced groups)
 * - Group → Project mappings
 * - Sync status and manual sync triggers
 */

import React, { useState, useEffect, useCallback } from 'react';
import './ProvisioningPanel.css';

// Types
interface ScimToken {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

interface ScimGroup {
  id: string;
  display_name: string;
  external_id: string | null;
  members_count: number;
  created_at: string;
}

interface GroupMapping {
  id: string;
  scim_group_id: string;
  group_display_name: string;
  project_id: string;
  project_name: string;
  role: 'viewer' | 'editor' | 'admin';
  enabled: boolean;
  created_at: string;
}

interface SyncStatus {
  scim_groups: number;
  enabled_mappings: number;
  scim_memberships: number;
  manual_memberships: number;
}

interface Project {
  id: string;
  name: string;
}

// Mock API functions (replace with actual API calls)
const api = {
  async getScimTokens(): Promise<ScimToken[]> {
    const response = await fetch('/api/provisioning/tokens');
    const data = await response.json();
    return data.tokens;
  },

  async createScimToken(name: string, expiresInDays?: number): Promise<{ token: ScimToken; plain_token: string }> {
    const response = await fetch('/api/provisioning/tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, expires_in_days: expiresInDays }),
    });
    return response.json();
  },

  async revokeScimToken(tokenId: string): Promise<void> {
    await fetch(`/api/provisioning/tokens/${tokenId}`, {
      method: 'DELETE',
    });
  },

  async getScimGroups(): Promise<ScimGroup[]> {
    const response = await fetch('/api/scim/v2/Groups');
    const data = await response.json();
    return data.Resources || [];
  },

  async getMappings(): Promise<GroupMapping[]> {
    const response = await fetch('/api/provisioning/mappings');
    const data = await response.json();
    return data.mappings;
  },

  async createMapping(scimGroupId: string, projectId: string, role: string): Promise<GroupMapping> {
    const response = await fetch('/api/provisioning/mappings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scim_group_id: scimGroupId, project_id: projectId, role }),
    });
    const data = await response.json();
    return data.mapping;
  },

  async updateMapping(mappingId: string, updates: { role?: string; enabled?: boolean }): Promise<GroupMapping> {
    const response = await fetch(`/api/provisioning/mappings/${mappingId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    const data = await response.json();
    return data.mapping;
  },

  async deleteMapping(mappingId: string): Promise<void> {
    await fetch(`/api/provisioning/mappings/${mappingId}`, {
      method: 'DELETE',
    });
  },

  async getSyncStatus(): Promise<SyncStatus> {
    const response = await fetch('/api/provisioning/mappings/status');
    return response.json();
  },

  async triggerSync(scimGroupId?: string): Promise<void> {
    await fetch('/api/provisioning/mappings/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scim_group_id: scimGroupId }),
    });
  },

  async getProjects(): Promise<Project[]> {
    const response = await fetch('/api/projects');
    const data = await response.json();
    return data.projects;
  },
};

// Sub-components
interface TokenCardProps {
  token: ScimToken;
  onRevoke: (id: string) => void;
}

const TokenCard: React.FC<TokenCardProps> = ({ token, onRevoke }) => {
  const isRevoked = !!token.revoked_at;
  const isExpired = token.expires_at && new Date(token.expires_at) < new Date();

  return (
    <div className={`token-card ${isRevoked ? 'revoked' : ''} ${isExpired ? 'expired' : ''}`}>
      <div className="token-header">
        <span className="token-name">{token.name}</span>
        <span className="token-prefix">{token.prefix}...</span>
      </div>
      <div className="token-meta">
        <span>Utworzony: {new Date(token.created_at).toLocaleDateString('pl-PL')}</span>
        {token.expires_at && (
          <span>Wygasa: {new Date(token.expires_at).toLocaleDateString('pl-PL')}</span>
        )}
        {token.last_used_at && (
          <span>Ostatnio użyty: {new Date(token.last_used_at).toLocaleDateString('pl-PL')}</span>
        )}
      </div>
      <div className="token-actions">
        {isRevoked ? (
          <span className="status-badge revoked">Unieważniony</span>
        ) : isExpired ? (
          <span className="status-badge expired">Wygasły</span>
        ) : (
          <button className="btn btn-danger btn-sm" onClick={() => onRevoke(token.id)}>
            Unieważnij
          </button>
        )}
      </div>
    </div>
  );
};

interface CreateTokenModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (token: ScimToken, plainToken: string) => void;
}

const CreateTokenModal: React.FC<CreateTokenModalProps> = ({ isOpen, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [expiresInDays, setExpiresInDays] = useState<number | undefined>(365);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const result = await api.createScimToken(name, expiresInDays);
      onCreated(result.token, result.plain_token);
      setName('');
      onClose();
    } catch (err) {
      console.error('Failed to create token:', err);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h3>Utwórz Token SCIM</h3>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Nazwa tokenu</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="np. Okta Production"
              required
            />
          </div>
          <div className="form-group">
            <label>Wygasa po (dni)</label>
            <input
              type="number"
              value={expiresInDays || ''}
              onChange={(e) => setExpiresInDays(e.target.value ? parseInt(e.target.value) : undefined)}
              placeholder="Pozostaw puste = nigdy"
              min="1"
            />
          </div>
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Anuluj
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading || !name}>
              {loading ? 'Tworzenie...' : 'Utwórz'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

interface TokenCreatedModalProps {
  isOpen: boolean;
  plainToken: string;
  onClose: () => void;
}

const TokenCreatedModal: React.FC<TokenCreatedModalProps> = ({ isOpen, plainToken, onClose }) => {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(plainToken);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h3>Token SCIM Utworzony</h3>
        <div className="alert alert-warning">
          <strong>Ważne:</strong> Skopiuj ten token teraz. Nie będzie można go ponownie wyświetlić.
        </div>
        <div className="token-display">
          <code>{plainToken}</code>
          <button className="btn btn-sm" onClick={copyToClipboard}>
            {copied ? '✓ Skopiowano' : 'Kopiuj'}
          </button>
        </div>
        <div className="modal-actions">
          <button className="btn btn-primary" onClick={onClose}>
            Rozumiem, zamknij
          </button>
        </div>
      </div>
    </div>
  );
};

interface MappingRowProps {
  mapping: GroupMapping;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
  onRoleChange: (id: string, role: string) => void;
}

const MappingRow: React.FC<MappingRowProps> = ({ mapping, onToggle, onDelete, onRoleChange }) => {
  return (
    <tr className={mapping.enabled ? '' : 'disabled'}>
      <td>{mapping.group_display_name}</td>
      <td>{mapping.project_name || mapping.project_id}</td>
      <td>
        <select
          value={mapping.role}
          onChange={(e) => onRoleChange(mapping.id, e.target.value)}
          disabled={!mapping.enabled}
        >
          <option value="viewer">Przeglądający</option>
          <option value="editor">Edytor</option>
          <option value="admin">Administrator</option>
        </select>
      </td>
      <td>
        <label className="toggle-switch">
          <input
            type="checkbox"
            checked={mapping.enabled}
            onChange={(e) => onToggle(mapping.id, e.target.checked)}
          />
          <span className="toggle-slider"></span>
        </label>
      </td>
      <td>
        <button className="btn btn-danger btn-sm" onClick={() => onDelete(mapping.id)}>
          Usuń
        </button>
      </td>
    </tr>
  );
};

interface CreateMappingModalProps {
  isOpen: boolean;
  groups: ScimGroup[];
  projects: Project[];
  onClose: () => void;
  onCreated: (mapping: GroupMapping) => void;
}

const CreateMappingModal: React.FC<CreateMappingModalProps> = ({
  isOpen,
  groups,
  projects,
  onClose,
  onCreated,
}) => {
  const [scimGroupId, setScimGroupId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [role, setRole] = useState('editor');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const mapping = await api.createMapping(scimGroupId, projectId, role);
      onCreated(mapping);
      setScimGroupId('');
      setProjectId('');
      setRole('editor');
      onClose();
    } catch (err) {
      console.error('Failed to create mapping:', err);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h3>Utwórz Mapowanie Grupy</h3>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Grupa SCIM</label>
            <select value={scimGroupId} onChange={(e) => setScimGroupId(e.target.value)} required>
              <option value="">Wybierz grupę...</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.display_name} ({g.members_count} członków)
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>Projekt</label>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
              <option value="">Wybierz projekt...</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>Rola</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="viewer">Przeglądający</option>
              <option value="editor">Edytor</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Anuluj
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading || !scimGroupId || !projectId}>
              {loading ? 'Tworzenie...' : 'Utwórz'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// Main component
const ProvisioningPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'tokens' | 'groups' | 'mappings'>('tokens');
  const [tokens, setTokens] = useState<ScimToken[]>([]);
  const [groups, setGroups] = useState<ScimGroup[]>([]);
  const [mappings, setMappings] = useState<GroupMapping[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(true);

  // Modal states
  const [showCreateToken, setShowCreateToken] = useState(false);
  const [showTokenCreated, setShowTokenCreated] = useState(false);
  const [createdPlainToken, setCreatedPlainToken] = useState('');
  const [showCreateMapping, setShowCreateMapping] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [tokensData, groupsData, mappingsData, projectsData, statusData] = await Promise.all([
        api.getScimTokens(),
        api.getScimGroups(),
        api.getMappings(),
        api.getProjects(),
        api.getSyncStatus(),
      ]);
      setTokens(tokensData);
      setGroups(groupsData);
      setMappings(mappingsData);
      setProjects(projectsData);
      setSyncStatus(statusData);
    } catch (err) {
      console.error('Failed to load provisioning data:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRevokeToken = async (tokenId: string) => {
    if (!window.confirm('Czy na pewno chcesz unieważnić ten token?')) return;
    try {
      await api.revokeScimToken(tokenId);
      setTokens((prev) => prev.map((t) => (t.id === tokenId ? { ...t, revoked_at: new Date().toISOString() } : t)));
    } catch (err) {
      console.error('Failed to revoke token:', err);
    }
  };

  const handleTokenCreated = (token: ScimToken, plainToken: string) => {
    setTokens((prev) => [token, ...prev]);
    setCreatedPlainToken(plainToken);
    setShowTokenCreated(true);
  };

  const handleToggleMapping = async (mappingId: string, enabled: boolean) => {
    try {
      const updated = await api.updateMapping(mappingId, { enabled });
      setMappings((prev) => prev.map((m) => (m.id === mappingId ? updated : m)));
    } catch (err) {
      console.error('Failed to toggle mapping:', err);
    }
  };

  const handleDeleteMapping = async (mappingId: string) => {
    if (!window.confirm('Czy na pewno chcesz usunąć to mapowanie? Członkostwa SCIM zostaną cofnięte.')) return;
    try {
      await api.deleteMapping(mappingId);
      setMappings((prev) => prev.filter((m) => m.id !== mappingId));
    } catch (err) {
      console.error('Failed to delete mapping:', err);
    }
  };

  const handleRoleChange = async (mappingId: string, role: string) => {
    try {
      const updated = await api.updateMapping(mappingId, { role });
      setMappings((prev) => prev.map((m) => (m.id === mappingId ? updated : m)));
    } catch (err) {
      console.error('Failed to update role:', err);
    }
  };

  const handleMappingCreated = (mapping: GroupMapping) => {
    setMappings((prev) => [mapping, ...prev]);
    loadData(); // Reload to get updated sync status
  };

  const handleTriggerSync = async () => {
    try {
      await api.triggerSync();
      loadData();
    } catch (err) {
      console.error('Failed to trigger sync:', err);
    }
  };

  if (loading) {
    return <div className="provisioning-panel loading">Ładowanie...</div>;
  }

  return (
    <div className="provisioning-panel">
      <div className="panel-header">
        <h2>Provisioning SCIM</h2>
        <div className="sync-status">
          {syncStatus && (
            <>
              <span className="status-item">
                <strong>{syncStatus.scim_groups}</strong> grup
              </span>
              <span className="status-item">
                <strong>{syncStatus.enabled_mappings}</strong> mapowań
              </span>
              <span className="status-item">
                <strong>{syncStatus.scim_memberships}</strong> członkostw SCIM
              </span>
              <button className="btn btn-sm" onClick={handleTriggerSync}>
                Synchronizuj teraz
              </button>
            </>
          )}
        </div>
      </div>

      <div className="tabs">
        <button className={activeTab === 'tokens' ? 'active' : ''} onClick={() => setActiveTab('tokens')}>
          Tokeny SCIM
        </button>
        <button className={activeTab === 'groups' ? 'active' : ''} onClick={() => setActiveTab('groups')}>
          Grupy SCIM
        </button>
        <button className={activeTab === 'mappings' ? 'active' : ''} onClick={() => setActiveTab('mappings')}>
          Mapowania
        </button>
      </div>

      <div className="tab-content">
        {activeTab === 'tokens' && (
          <div className="tokens-section">
            <div className="section-header">
              <h3>Tokeny SCIM</h3>
              <button className="btn btn-primary" onClick={() => setShowCreateToken(true)}>
                + Utwórz token
              </button>
            </div>
            <div className="tokens-grid">
              {tokens.length === 0 ? (
                <p className="empty-state">Brak tokenów SCIM. Utwórz token, aby umożliwić integrację z IdP.</p>
              ) : (
                tokens.map((token) => (
                  <TokenCard key={token.id} token={token} onRevoke={handleRevokeToken} />
                ))
              )}
            </div>
          </div>
        )}

        {activeTab === 'groups' && (
          <div className="groups-section">
            <div className="section-header">
              <h3>Grupy SCIM</h3>
              <span className="info-text">Grupy są zarządzane przez IdP poprzez SCIM</span>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Nazwa grupy</th>
                  <th>External ID</th>
                  <th>Członkowie</th>
                  <th>Utworzono</th>
                </tr>
              </thead>
              <tbody>
                {groups.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="empty-state">
                      Brak grup SCIM. Grupy zostaną zsynchronizowane po konfiguracji IdP.
                    </td>
                  </tr>
                ) : (
                  groups.map((group) => (
                    <tr key={group.id}>
                      <td>{group.display_name}</td>
                      <td>{group.external_id || '-'}</td>
                      <td>{group.members_count}</td>
                      <td>{new Date(group.created_at).toLocaleDateString('pl-PL')}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'mappings' && (
          <div className="mappings-section">
            <div className="section-header">
              <h3>Mapowania Grup → Projekty</h3>
              <button className="btn btn-primary" onClick={() => setShowCreateMapping(true)}>
                + Dodaj mapowanie
              </button>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Grupa SCIM</th>
                  <th>Projekt</th>
                  <th>Rola</th>
                  <th>Aktywne</th>
                  <th>Akcje</th>
                </tr>
              </thead>
              <tbody>
                {mappings.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="empty-state">
                      Brak mapowań. Dodaj mapowanie, aby przypisać grupy SCIM do projektów.
                    </td>
                  </tr>
                ) : (
                  mappings.map((mapping) => (
                    <MappingRow
                      key={mapping.id}
                      mapping={mapping}
                      onToggle={handleToggleMapping}
                      onDelete={handleDeleteMapping}
                      onRoleChange={handleRoleChange}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <CreateTokenModal
        isOpen={showCreateToken}
        onClose={() => setShowCreateToken(false)}
        onCreated={handleTokenCreated}
      />

      <TokenCreatedModal
        isOpen={showTokenCreated}
        plainToken={createdPlainToken}
        onClose={() => setShowTokenCreated(false)}
      />

      <CreateMappingModal
        isOpen={showCreateMapping}
        groups={groups}
        projects={projects}
        onClose={() => setShowCreateMapping(false)}
        onCreated={handleMappingCreated}
      />
    </div>
  );
};

export default ProvisioningPanel;
