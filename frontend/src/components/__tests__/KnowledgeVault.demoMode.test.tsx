import { act, render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { KnowledgeVault } from '../KnowledgeVault';
import { useConfigStore } from '../../stores/configStore';
import { useDocumentStore } from '../../stores/documentStore';

const fetchCollections = vi.fn();
const sampleCollection = {
  id: 3, user_id: 2, name: 'SAMPLE Clients (synthetic)', description: null,
  document_count: 7, created_at: '', updated_at: '',
};

describe('Client Files pane (CPA demo mode)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDocumentStore.setState({
      collections: [], documents: [], selectedCollectionId: null, isLoading: false, fetchCollections,
    } as never);
  });

  it('flag on: heading reads "Client Files" and the pane is open on first load and fetches collections', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    render(<KnowledgeVault />);
    const header = screen.getByRole('button', { name: /Client Files/ });
    expect(header).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByText('Knowledge Vault')).not.toBeInTheDocument();
    expect(fetchCollections).toHaveBeenCalledTimes(1);
  });

  it('flag on: lists the synthetic client folders without an extra click', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    useDocumentStore.setState({ collections: [sampleCollection] } as never);
    render(<KnowledgeVault />);
    expect(screen.getByText('SAMPLE Clients (synthetic)')).toBeInTheDocument();
  });

  it('flag on: the user can still collapse it', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    render(<KnowledgeVault />);
    fireEvent.click(screen.getByRole('button', { name: /Client Files/ }));
    expect(screen.getByRole('button', { name: /Client Files/ })).toHaveAttribute('aria-expanded', 'false');
  });

  it('flag off: heading stays "Knowledge Vault" and the pane starts collapsed', () => {
    useConfigStore.setState({ demoMode: false, firmName: '', loaded: true });
    render(<KnowledgeVault />);
    const header = screen.getByRole('button', { name: /Knowledge Vault/ });
    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Client Files')).not.toBeInTheDocument();
    expect(fetchCollections).not.toHaveBeenCalled();
  });

  it('opens once the runtime flag arrives after first render', () => {
    useConfigStore.setState({ demoMode: false, firmName: '', loaded: false });
    render(<KnowledgeVault />);
    expect(screen.getByRole('button', { name: /Knowledge Vault/ })).toHaveAttribute('aria-expanded', 'false');
    act(() => useConfigStore.setState({ demoMode: true, loaded: true }));
    expect(screen.getByRole('button', { name: /Client Files/ })).toHaveAttribute('aria-expanded', 'true');
  });
});
