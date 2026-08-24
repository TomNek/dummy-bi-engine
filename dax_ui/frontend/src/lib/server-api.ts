/**
 * API client for the Report Server management UI
 * All requests go through Vite's proxy at /server/*
 */

const BASE_URL = '/server'

interface ServerApiResponse<T> {
  data?: T
  error?: string
  status?: number
}

async function serverApiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ServerApiResponse<T>> {
  const url = `${BASE_URL}${endpoint}`

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })

    if (!response.ok) {
      const errorText = await response.text()
      return { error: errorText || `HTTP ${response.status}`, status: response.status }
    }

    const data = await response.json()
    if (data.ok === false) {
      return { error: data.error || 'Unknown error', status: response.status }
    }
    return { data: data.data ?? data, status: response.status }
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Unknown error' }
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Environment {
  name: string
  display_name: string
  color: string
  description: string
  catalog_dir: string
  created_at: string
  is_default?: boolean
}

export interface FolderInfo {
  name: string
  path: string
  display_name: string
  description: string
  icon: string
  sort_order: number
  created_at: string
}

export interface FolderContents {
  folder: FolderInfo
  subfolders: FolderInfo[]
  definitions: string[]
}

export interface Pipeline {
  name: string
  display_name: string
  description?: string
  stages: PipelineStage[]
  created_at: string
}

export interface PipelineStage {
  environment: string
  order: number
  folder_path?: string | null
}

export interface DeploymentRecord {
  id: string
  pipeline_name: string
  from_stage: number
  to_stage: number
  deployed_at: string
  deployed_by: string
  items_deployed: number
  status: string
}

export interface GitCommitInfo {
  sha: string
  author: string
  date: string
  message: string
  files_changed: number
}

export interface CompareResult {
  from_stage: string
  to_stage: string
  differences: Array<{ path: string; status: string }>
}

// ---------------------------------------------------------------------------
// Environments
// ---------------------------------------------------------------------------

export async function listEnvironments(): Promise<Environment[]> {
  const res = await serverApiRequest<{ environments: Environment[] }>('/environments')
  return res.data?.environments ?? []
}

export async function getEnvironment(name: string): Promise<Environment> {
  const res = await serverApiRequest<{ environment: Environment }>(`/environments/${encodeURIComponent(name)}`)
  if (res.error || !res.data?.environment) throw new Error(res.error ?? 'Environment not found')
  return res.data.environment
}

export async function createEnvironment(data: { name: string; description?: string }): Promise<Environment> {
  const res = await serverApiRequest<{ environment: Environment }>('/environments', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (res.error || !res.data?.environment) throw new Error(res.error ?? 'Failed to create environment')
  return res.data.environment
}

export async function updateEnvironment(
  name: string,
  data: Partial<Pick<Environment, 'description' | 'is_default'>>
): Promise<Environment> {
  const res = await serverApiRequest<{ environment: Environment }>(`/environments/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (res.error || !res.data?.environment) throw new Error(res.error ?? 'Failed to update environment')
  return res.data.environment
}

export async function deleteEnvironment(name: string): Promise<void> {
  const res = await serverApiRequest<Record<string, unknown>>(`/environments/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
  if (res.error) throw new Error(res.error)
}

// ---------------------------------------------------------------------------
// Folders
// ---------------------------------------------------------------------------

export async function listFolders(environment: string): Promise<FolderInfo[]> {
  const res = await serverApiRequest<{ folders: FolderInfo[] }>(
    `/folders?environment=${encodeURIComponent(environment)}`
  )
  return res.data?.folders ?? []
}

export async function getFolder(path: string, environment: string): Promise<FolderContents> {
  const res = await serverApiRequest<FolderContents>(
    `/folders/${encodeURIComponent(path)}?environment=${encodeURIComponent(environment)}`
  )
  if (res.error || !res.data) throw new Error(res.error ?? 'Folder not found')
  return res.data
}

export async function createFolder(
  data: { name: string; parent?: string; description?: string },
  environment: string
): Promise<FolderInfo> {
  const res = await serverApiRequest<{ folder: FolderInfo }>(
    `/folders?environment=${encodeURIComponent(environment)}`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  )
  if (res.error || !res.data?.folder) throw new Error(res.error ?? 'Failed to create folder')
  return res.data.folder
}

export async function updateFolder(
  path: string,
  data: Partial<Pick<FolderInfo, 'name' | 'description'>>,
  environment: string
): Promise<FolderInfo> {
  const res = await serverApiRequest<{ folder: FolderInfo }>(
    `/folders/${encodeURIComponent(path)}?environment=${encodeURIComponent(environment)}`,
    {
      method: 'PUT',
      body: JSON.stringify(data),
    }
  )
  if (res.error || !res.data?.folder) throw new Error(res.error ?? 'Failed to update folder')
  return res.data.folder
}

export async function deleteFolder(path: string, environment: string): Promise<void> {
  const res = await serverApiRequest<Record<string, unknown>>(
    `/folders/${encodeURIComponent(path)}?environment=${encodeURIComponent(environment)}`,
    { method: 'DELETE' }
  )
  if (res.error) throw new Error(res.error)
}

// ---------------------------------------------------------------------------
// Pipelines
// ---------------------------------------------------------------------------

export async function listPipelines(): Promise<Pipeline[]> {
  const res = await serverApiRequest<{ pipelines: Pipeline[] }>('/pipelines')
  return res.data?.pipelines ?? []
}

export async function getPipeline(name: string): Promise<Pipeline> {
  const res = await serverApiRequest<{ pipeline: Pipeline }>(`/pipelines/${encodeURIComponent(name)}`)
  if (res.error || !res.data?.pipeline) throw new Error(res.error ?? 'Pipeline not found')
  return res.data.pipeline
}

export async function createPipeline(data: {
  name: string
  description?: string
  stages: PipelineStage[]
}): Promise<Pipeline> {
  const res = await serverApiRequest<{ pipeline: Pipeline }>('/pipelines', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (res.error || !res.data?.pipeline) throw new Error(res.error ?? 'Failed to create pipeline')
  return res.data.pipeline
}

export async function updatePipeline(
  name: string,
  data: Partial<Pick<Pipeline, 'description' | 'stages'>>
): Promise<Pipeline> {
  const res = await serverApiRequest<{ pipeline: Pipeline }>(`/pipelines/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (res.error || !res.data?.pipeline) throw new Error(res.error ?? 'Failed to update pipeline')
  return res.data.pipeline
}

export async function deletePipeline(name: string): Promise<void> {
  const res = await serverApiRequest<Record<string, unknown>>(`/pipelines/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
  if (res.error) throw new Error(res.error)
}

export async function comparePipelineStages(
  name: string,
  fromStage: number,
  toStage: number,
  folderPath?: string | null
): Promise<CompareResult> {
  let url = `/pipelines/${encodeURIComponent(name)}/compare?from_stage=${fromStage}&to_stage=${toStage}`
  if (folderPath) url += `&folder_path=${encodeURIComponent(folderPath)}`
  const res = await serverApiRequest<{ comparison: CompareResult } & CompareResult>(url)
  if (res.error || !res.data) throw new Error(res.error ?? 'Failed to compare stages')
  // Backend wraps result in "comparison" key
  return res.data.comparison ?? res.data
}

export async function deployPipeline(
  name: string,
  data: { from_stage: number; to_stage: number; folder_path?: string | null }
): Promise<DeploymentRecord> {
  const res = await serverApiRequest<{ deployment: DeploymentRecord }>(
    `/pipelines/${encodeURIComponent(name)}/deploy`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  )
  if (res.error || !res.data?.deployment) throw new Error(res.error ?? 'Deployment failed')
  return res.data.deployment
}

export async function getPipelineHistory(name: string): Promise<DeploymentRecord[]> {
  const res = await serverApiRequest<{ history: DeploymentRecord[] }>(
    `/pipelines/${encodeURIComponent(name)}/history`
  )
  return res.data?.history ?? []
}

export async function rollbackDeployment(
  name: string,
  data: { deployment_id: string }
): Promise<DeploymentRecord> {
  const res = await serverApiRequest<{ deployment: DeploymentRecord }>(
    `/pipelines/${encodeURIComponent(name)}/rollback`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  )
  if (res.error || !res.data?.deployment) throw new Error(res.error ?? 'Rollback failed')
  return res.data.deployment
}

// ---------------------------------------------------------------------------
// Git History
// ---------------------------------------------------------------------------

export async function getEnvironmentHistory(
  name: string,
  limit?: number
): Promise<GitCommitInfo[]> {
  const params = limit != null ? `?limit=${limit}` : ''
  const res = await serverApiRequest<{ commits: GitCommitInfo[] }>(
    `/environments/${encodeURIComponent(name)}/history${params}`
  )
  return res.data?.commits ?? []
}

export async function getCommitDetail(
  envName: string,
  hash: string
): Promise<GitCommitInfo> {
  const res = await serverApiRequest<{ commit: GitCommitInfo }>(
    `/environments/${encodeURIComponent(envName)}/history/${encodeURIComponent(hash)}`
  )
  if (res.error || !res.data?.commit) throw new Error(res.error ?? 'Commit not found')
  return res.data.commit
}

export async function revertCommit(
  envName: string,
  hash: string
): Promise<GitCommitInfo> {
  const res = await serverApiRequest<{ commit: GitCommitInfo }>(
    `/environments/${encodeURIComponent(envName)}/revert/${encodeURIComponent(hash)}`,
    { method: 'POST' }
  )
  if (res.error || !res.data?.commit) throw new Error(res.error ?? 'Revert failed')
  return res.data.commit
}

export async function getEnvironmentDiff(
  envName: string,
  from?: string,
  to?: string
): Promise<string> {
  const params = new URLSearchParams()
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const res = await serverApiRequest<{ diff: string }>(
    `/environments/${encodeURIComponent(envName)}/diff${qs}`
  )
  if (res.error) throw new Error(res.error)
  return res.data?.diff ?? ''
}

export async function getRemoteConfig(
  envName: string
): Promise<{ url: string; branch: string } | null> {
  const res = await serverApiRequest<{ remote: { url: string; branch: string } | null }>(
    `/environments/${encodeURIComponent(envName)}/remote`
  )
  if (res.error) throw new Error(res.error)
  return res.data?.remote ?? null
}

export async function setRemoteConfig(
  envName: string,
  data: { url: string; branch?: string }
): Promise<{ url: string; branch: string }> {
  const res = await serverApiRequest<{ remote: { url: string; branch: string } }>(
    `/environments/${encodeURIComponent(envName)}/remote`,
    {
      method: 'PUT',
      body: JSON.stringify(data),
    }
  )
  if (res.error || !res.data?.remote) throw new Error(res.error ?? 'Failed to set remote')
  return res.data.remote
}

export async function removeRemote(envName: string): Promise<void> {
  const res = await serverApiRequest<Record<string, unknown>>(
    `/environments/${encodeURIComponent(envName)}/remote`,
    { method: 'DELETE' }
  )
  if (res.error) throw new Error(res.error)
}

export async function pushToRemote(envName: string): Promise<{ message: string }> {
  const res = await serverApiRequest<{ message: string }>(
    `/environments/${encodeURIComponent(envName)}/push`,
    { method: 'POST' }
  )
  if (res.error) throw new Error(res.error)
  return { message: res.data?.message ?? 'Push completed' }
}

export async function pullFromRemote(envName: string): Promise<{ message: string }> {
  const res = await serverApiRequest<{ message: string }>(
    `/environments/${encodeURIComponent(envName)}/pull`,
    { method: 'POST' }
  )
  if (res.error) throw new Error(res.error)
  return { message: res.data?.message ?? 'Pull completed' }
}

// ---------------------------------------------------------------------------
// Configurations
// ---------------------------------------------------------------------------

export interface ReportConfiguration {
  id: string
  definition_id: string
  definition_version: number
  name: string
  default_slicer_values: Record<string, unknown>
  default_filter_values: Record<string, unknown>
  execution_mode: string
  cache_policy: Record<string, unknown>
  permissions: Record<string, unknown>
  stable_url_slug: string
}

export async function getConfiguration(configId: string): Promise<ReportConfiguration> {
  const res = await serverApiRequest<{ configuration: ReportConfiguration } & ReportConfiguration>(
    `/configurations/${encodeURIComponent(configId)}`
  )
  if (res.error || !res.data) throw new Error(res.error ?? 'Configuration not found')
  return res.data.configuration ?? (res.data as unknown as ReportConfiguration)
}

export async function createConfiguration(
  data: Record<string, unknown>
): Promise<ReportConfiguration> {
  const res = await serverApiRequest<{ configuration: ReportConfiguration }>(
    '/configurations',
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  )
  if (res.error || !res.data) throw new Error(res.error ?? 'Failed to create configuration')
  return res.data.configuration ?? (res.data as unknown as ReportConfiguration)
}

export async function cloneConfiguration(
  configId: string,
  newName: string,
  overrides?: Record<string, unknown>
): Promise<ReportConfiguration> {
  const res = await serverApiRequest<{ configuration: ReportConfiguration }>(
    `/configurations/${encodeURIComponent(configId)}/clone`,
    {
      method: 'POST',
      body: JSON.stringify({ name: newName, overrides: overrides ?? {} }),
    }
  )
  if (res.error) throw new Error(res.error)
  return res.data?.configuration ?? (res.data as unknown as ReportConfiguration)
}

/**
 * Download a configuration as a JSON file in the browser.
 */
export async function exportConfiguration(configId: string): Promise<void> {
  const config = await getConfiguration(configId)
  const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `configuration-${config.name || configId}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Import a configuration from uploaded JSON data.
 */
export async function importConfiguration(
  data: Record<string, unknown>
): Promise<ReportConfiguration> {
  return createConfiguration(data)
}

// ---------------------------------------------------------------------------
// Definitions
// ---------------------------------------------------------------------------

export async function getDefinition(definitionId: string): Promise<Record<string, unknown>> {
  const res = await serverApiRequest<Record<string, unknown>>(
    `/definitions/${encodeURIComponent(definitionId)}`
  )
  if (res.error || !res.data) throw new Error(res.error ?? 'Definition not found')
  return res.data
}

export async function uploadDefinition(
  data: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const res = await serverApiRequest<Record<string, unknown>>(
    '/definitions/upload',
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  )
  if (res.error || !res.data) throw new Error(res.error ?? 'Failed to upload definition')
  return res.data
}

/**
 * Download a definition as a JSON file in the browser.
 */
export async function exportDefinition(definitionId: string): Promise<void> {
  const def = await getDefinition(definitionId)
  const name = (def as { name?: string }).name || definitionId
  const blob = new Blob([JSON.stringify(def, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `definition-${name}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Import a definition from uploaded JSON data.
 */
export async function importDefinition(
  data: Record<string, unknown>
): Promise<Record<string, unknown>> {
  return uploadDefinition(data)
}

// ---------------------------------------------------------------------------
// Security (Phase 14i)
// ---------------------------------------------------------------------------

export interface RoleAssignment {
  id: string
  identity_type: 'local' | 'aad_group'
  identity: string
  role: string
  description: string
}

export interface SecurityProviders {
  aad: { enabled: boolean; tenant_id: string }
  local: { enabled: boolean }
}

export interface SecurityConfig {
  providers: SecurityProviders
  role_assignments: RoleAssignment[]
  default_role: string
}

export interface CurrentRole {
  role: string
  level: number
  sections: string[]
}

export async function getSecurityConfig(): Promise<SecurityConfig> {
  const res = await serverApiRequest<{ config: SecurityConfig }>('/security/config')
  if (res.error) throw new Error(res.error)
  return res.data?.config ?? (res.data as unknown as SecurityConfig)
}

export async function updateSecurityConfig(updates: {
  default_role?: string
  aad_enabled?: boolean
  aad_tenant_id?: string
  local_enabled?: boolean
}): Promise<SecurityConfig> {
  const res = await serverApiRequest<{ config: SecurityConfig }>('/security/config', {
    method: 'PUT',
    body: JSON.stringify(updates),
  })
  if (res.error) throw new Error(res.error)
  return res.data?.config ?? (res.data as unknown as SecurityConfig)
}

export async function listRoleAssignments(): Promise<RoleAssignment[]> {
  const res = await serverApiRequest<{ assignments: RoleAssignment[] }>('/security/roles')
  if (res.error) throw new Error(res.error)
  return res.data?.assignments ?? []
}

export async function createRoleAssignment(data: {
  identity_type: string
  identity: string
  role: string
  description?: string
}): Promise<RoleAssignment> {
  const res = await serverApiRequest<{ assignment: RoleAssignment }>('/security/roles', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (res.error) throw new Error(res.error)
  return res.data?.assignment ?? (res.data as unknown as RoleAssignment)
}

export async function updateRoleAssignment(
  id: string,
  updates: { role?: string; description?: string }
): Promise<RoleAssignment> {
  const res = await serverApiRequest<{ assignment: RoleAssignment }>(
    `/security/roles/${encodeURIComponent(id)}`,
    { method: 'PUT', body: JSON.stringify(updates) }
  )
  if (res.error) throw new Error(res.error)
  return res.data?.assignment ?? (res.data as unknown as RoleAssignment)
}

export async function deleteRoleAssignment(id: string): Promise<void> {
  const res = await serverApiRequest(`/security/roles/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (res.error) throw new Error(res.error)
}

export async function getSecurityProviders(): Promise<SecurityProviders> {
  const res = await serverApiRequest<{ providers: SecurityProviders }>('/security/providers')
  if (res.error) throw new Error(res.error)
  return res.data?.providers ?? (res.data as unknown as SecurityProviders)
}

export async function updateSecurityProviders(updates: {
  aad_enabled?: boolean
  aad_tenant_id?: string
  local_enabled?: boolean
}): Promise<SecurityProviders> {
  const res = await serverApiRequest<{ providers: SecurityProviders }>('/security/providers', {
    method: 'PUT',
    body: JSON.stringify(updates),
  })
  if (res.error) throw new Error(res.error)
  return res.data?.providers ?? (res.data as unknown as SecurityProviders)
}

export async function getCurrentRole(): Promise<CurrentRole> {
  const res = await serverApiRequest<CurrentRole>('/security/current-role')
  if (res.error) throw new Error(res.error)
  return res.data as CurrentRole
}

// ---------------------------------------------------------------------------
// Auth / Report-Server Connection
// ---------------------------------------------------------------------------

export interface AuthStatus {
  connected: boolean
  server_url: string | null
  user: string | null
  server_name: string | null
}

export interface Workspace {
  id: string
  name: string
}

export async function serverLogin(
  url: string,
  username: string,
  password: string
): Promise<AuthStatus> {
  const res = await serverApiRequest<AuthStatus>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ url, username, password }),
  })
  if (res.error) throw new Error(res.error)
  return res.data as AuthStatus
}

export async function serverLogout(): Promise<void> {
  const res = await serverApiRequest('/auth/logout', { method: 'POST' })
  if (res.error) throw new Error(res.error)
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const res = await serverApiRequest<AuthStatus>('/auth/status')
  if (res.error) throw new Error(res.error)
  return res.data as AuthStatus
}

export async function getWorkspaces(): Promise<Workspace[]> {
  const res = await serverApiRequest<{ workspaces: Workspace[] }>('/workspaces')
  if (res.error) throw new Error(res.error)
  return res.data?.workspaces ?? []
}

export async function publishToServer(config: {
  definition_id?: string
  workspace: string
  target_folder?: string
}): Promise<{ published: boolean; message: string }> {
  const res = await serverApiRequest<{ published: boolean; message: string }>('/publish', {
    method: 'POST',
    body: JSON.stringify(config),
  })
  if (res.error) throw new Error(res.error)
  return res.data as { published: boolean; message: string }
}
