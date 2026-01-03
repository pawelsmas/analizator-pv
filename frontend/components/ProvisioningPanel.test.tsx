/**
 * ProvisioningPanel Tests (v4.4.0 PR9)
 *
 * Unit tests for SCIM Provisioning Management panel.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProvisioningPanel from './ProvisioningPanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock clipboard
Object.assign(navigator, {
  clipboard: {
    writeText: jest.fn().mockResolvedValue(undefined),
  },
});

// Test data
const mockTokens = [
  {
    id: 'token-1',
    name: 'Okta Production',
    prefix: 'scim_abc',
    created_at: '2024-01-01T00:00:00Z',
    expires_at: '2025-01-01T00:00:00Z',
    last_used_at: '2024-06-01T00:00:00Z',
    revoked_at: null,
  },
  {
    id: 'token-2',
    name: 'Azure AD Test',
    prefix: 'scim_def',
    created_at: '2024-02-01T00:00:00Z',
    expires_at: null,
    last_used_at: null,
    revoked_at: '2024-03-01T00:00:00Z',
  },
];

const mockGroups = [
  {
    id: 'group-1',
    display_name: 'Engineering',
    external_id: 'eng-001',
    members_count: 15,
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'group-2',
    display_name: 'Sales',
    external_id: null,
    members_count: 8,
    created_at: '2024-02-01T00:00:00Z',
  },
];

const mockMappings = [
  {
    id: 'mapping-1',
    scim_group_id: 'group-1',
    group_display_name: 'Engineering',
    project_id: 'project-1',
    project_name: 'Main Project',
    role: 'editor' as const,
    enabled: true,
    created_at: '2024-01-01T00:00:00Z',
  },
];

const mockProjects = [
  { id: 'project-1', name: 'Main Project' },
  { id: 'project-2', name: 'Secondary Project' },
];

const mockSyncStatus = {
  scim_groups: 2,
  enabled_mappings: 1,
  scim_memberships: 15,
  manual_memberships: 5,
};

// Helper to setup mock responses
const setupMocks = () => {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/provisioning/tokens')) {
      return Promise.resolve({
        json: () => Promise.resolve({ tokens: mockTokens }),
      });
    }
    if (url.includes('/api/scim/v2/Groups')) {
      return Promise.resolve({
        json: () => Promise.resolve({ Resources: mockGroups }),
      });
    }
    if (url.includes('/api/provisioning/mappings/status')) {
      return Promise.resolve({
        json: () => Promise.resolve(mockSyncStatus),
      });
    }
    if (url.includes('/api/provisioning/mappings')) {
      return Promise.resolve({
        json: () => Promise.resolve({ mappings: mockMappings }),
      });
    }
    if (url.includes('/api/projects')) {
      return Promise.resolve({
        json: () => Promise.resolve({ projects: mockProjects }),
      });
    }
    return Promise.reject(new Error('Unknown URL'));
  });
};

describe('ProvisioningPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupMocks();
  });

  describe('Initial Rendering', () => {
    it('shows loading state initially', () => {
      render(<ProvisioningPanel />);
      expect(screen.getByText('Ładowanie...')).toBeInTheDocument();
    });

    it('renders panel header after loading', async () => {
      render(<ProvisioningPanel />);
      await waitFor(() => {
        expect(screen.getByText('Provisioning SCIM')).toBeInTheDocument();
      });
    });

    it('displays sync status in header', async () => {
      render(<ProvisioningPanel />);
      await waitFor(() => {
        expect(screen.getByText('2')).toBeInTheDocument(); // scim_groups
        expect(screen.getByText('1')).toBeInTheDocument(); // enabled_mappings
        expect(screen.getByText('15')).toBeInTheDocument(); // scim_memberships
      });
    });

    it('renders all tabs', async () => {
      render(<ProvisioningPanel />);
      await waitFor(() => {
        expect(screen.getByText('Tokeny SCIM')).toBeInTheDocument();
        expect(screen.getByText('Grupy SCIM')).toBeInTheDocument();
        expect(screen.getByText('Mapowania')).toBeInTheDocument();
      });
    });
  });

  describe('Tokens Tab', () => {
    it('displays token cards', async () => {
      render(<ProvisioningPanel />);
      await waitFor(() => {
        expect(screen.getByText('Okta Production')).toBeInTheDocument();
        expect(screen.getByText('Azure AD Test')).toBeInTheDocument();
      });
    });

    it('shows token prefix', async () => {
      render(<ProvisioningPanel />);
      await waitFor(() => {
        expect(screen.getByText('scim_abc...')).toBeInTheDocument();
      });
    });

    it('shows revoked status for revoked tokens', async () => {
      render(<ProvisioningPanel />);
      await waitFor(() => {
        expect(screen.getByText('Unieważniony')).toBeInTheDocument();
      });
    });

    it('shows revoke button for active tokens', async () => {
      render(<ProvisioningPanel />);
      await waitFor(() => {
        expect(screen.getByText('Unieważnij')).toBeInTheDocument();
      });
    });

    it('opens create token modal when button clicked', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('+ Utwórz token')).toBeInTheDocument();
      });

      await user.click(screen.getByText('+ Utwórz token'));

      expect(screen.getByText('Utwórz Token SCIM')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('np. Okta Production')).toBeInTheDocument();
    });
  });

  describe('Groups Tab', () => {
    it('switches to groups tab when clicked', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Grupy SCIM')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Grupy SCIM' }));

      expect(screen.getByText('Engineering')).toBeInTheDocument();
      expect(screen.getByText('Sales')).toBeInTheDocument();
    });

    it('displays group member counts', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Grupy SCIM')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Grupy SCIM' }));

      expect(screen.getByText('15')).toBeInTheDocument();
      expect(screen.getByText('8')).toBeInTheDocument();
    });

    it('shows external ID when available', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Grupy SCIM')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Grupy SCIM' }));

      expect(screen.getByText('eng-001')).toBeInTheDocument();
    });
  });

  describe('Mappings Tab', () => {
    it('switches to mappings tab when clicked', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Mapowania')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Mapowania' }));

      expect(screen.getByText('Mapowania Grup → Projekty')).toBeInTheDocument();
    });

    it('displays existing mappings', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Mapowania')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Mapowania' }));

      expect(screen.getByText('Engineering')).toBeInTheDocument();
      expect(screen.getByText('Main Project')).toBeInTheDocument();
    });

    it('opens create mapping modal when button clicked', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Mapowania')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Mapowania' }));
      await user.click(screen.getByText('+ Dodaj mapowanie'));

      expect(screen.getByText('Utwórz Mapowanie Grupy')).toBeInTheDocument();
    });

    it('shows toggle switch for mapping enabled state', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Mapowania')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Mapowania' }));

      const toggles = screen.getAllByRole('checkbox');
      expect(toggles.length).toBeGreaterThan(0);
      expect(toggles[0]).toBeChecked();
    });

    it('shows delete button for mappings', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Mapowania')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Mapowania' }));

      expect(screen.getByText('Usuń')).toBeInTheDocument();
    });
  });

  describe('Sync Actions', () => {
    it('has sync now button in header', async () => {
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Synchronizuj teraz')).toBeInTheDocument();
      });
    });

    it('triggers sync when button clicked', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/provisioning/mappings/sync') && options?.method === 'POST') {
          return Promise.resolve({ json: () => Promise.resolve({}) });
        }
        // Default responses
        if (url.includes('/api/provisioning/tokens')) {
          return Promise.resolve({ json: () => Promise.resolve({ tokens: mockTokens }) });
        }
        if (url.includes('/api/scim/v2/Groups')) {
          return Promise.resolve({ json: () => Promise.resolve({ Resources: mockGroups }) });
        }
        if (url.includes('/api/provisioning/mappings/status')) {
          return Promise.resolve({ json: () => Promise.resolve(mockSyncStatus) });
        }
        if (url.includes('/api/provisioning/mappings')) {
          return Promise.resolve({ json: () => Promise.resolve({ mappings: mockMappings }) });
        }
        if (url.includes('/api/projects')) {
          return Promise.resolve({ json: () => Promise.resolve({ projects: mockProjects }) });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('Synchronizuj teraz')).toBeInTheDocument();
      });

      await user.click(screen.getByText('Synchronizuj teraz'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/provisioning/mappings/sync',
          expect.objectContaining({ method: 'POST' })
        );
      });
    });
  });

  describe('Empty States', () => {
    it('shows empty state for tokens when none exist', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/provisioning/tokens')) {
          return Promise.resolve({ json: () => Promise.resolve({ tokens: [] }) });
        }
        if (url.includes('/api/scim/v2/Groups')) {
          return Promise.resolve({ json: () => Promise.resolve({ Resources: [] }) });
        }
        if (url.includes('/api/provisioning/mappings/status')) {
          return Promise.resolve({ json: () => Promise.resolve(mockSyncStatus) });
        }
        if (url.includes('/api/provisioning/mappings')) {
          return Promise.resolve({ json: () => Promise.resolve({ mappings: [] }) });
        }
        if (url.includes('/api/projects')) {
          return Promise.resolve({ json: () => Promise.resolve({ projects: [] }) });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText(/Brak tokenów SCIM/)).toBeInTheDocument();
      });
    });
  });

  describe('Modal Interactions', () => {
    it('closes create token modal on cancel', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('+ Utwórz token')).toBeInTheDocument();
      });

      await user.click(screen.getByText('+ Utwórz token'));
      expect(screen.getByText('Utwórz Token SCIM')).toBeInTheDocument();

      await user.click(screen.getByText('Anuluj'));

      await waitFor(() => {
        expect(screen.queryByText('Utwórz Token SCIM')).not.toBeInTheDocument();
      });
    });

    it('disables submit button when name is empty', async () => {
      const user = userEvent.setup();
      render(<ProvisioningPanel />);

      await waitFor(() => {
        expect(screen.getByText('+ Utwórz token')).toBeInTheDocument();
      });

      await user.click(screen.getByText('+ Utwórz token'));

      const submitButton = screen.getByText('Utwórz');
      expect(submitButton).toBeDisabled();
    });
  });
});
