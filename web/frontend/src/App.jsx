import { useState, useEffect } from 'react';
import axios from 'axios';
import { Search, Server, Key, AlertCircle, Trash2, RotateCw, Tag, CheckSquare, Square, Users, User, Folder, Scissors, ChevronLeft, ChevronRight, X } from 'lucide-react';

const API_BASE = '/api';

function App() {
  const [serverUrl, setServerUrl] = useState(() => localStorage.getItem('pic_serverUrl') || '');
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('pic_apiKey') || '');
  const [mode, setMode] = useState('smart'); // 'smart', 'people', 'folder'
  const [folders, setFolders] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState('');
  
  const [query, setQuery] = useState('');
  const [people, setPeople] = useState([]);
  
  const [configSavedMsg, setConfigSavedMsg] = useState(false);
  const [testConnMsg, setTestConnMsg] = useState('');
  
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [error, setError] = useState('');
  
  // Mass Edit State
  const [selectedPaths, setSelectedPaths] = useState(new Set());
  const [tagInput, setTagInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  
  // Image Viewer State
  const [viewingIndex, setViewingIndex] = useState(-1);
  const viewingAsset = viewingIndex >= 0 ? results[viewingIndex] : null;
  const [viewerTags, setViewerTags] = useState([]);

  useEffect(() => {
    if (viewingAsset && viewingAsset.originalPath) {
      setViewerTags([]); // clear while loading
      axios.get(`${API_BASE}/tags?path=${encodeURIComponent(viewingAsset.originalPath)}`)
        .then(res => setViewerTags(res.data.tags || []))
        .catch(err => console.error("Failed to load tags", err));
    }
  }, [viewingAsset]);

  // Load folders on mount
  useEffect(() => {
    axios.get(`${API_BASE}/folders`).then(res => {
      setFolders(res.data.folders || []);
    }).catch(console.error);
  }, []);

  // Keyboard navigation for image viewer
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (viewingIndex >= 0) {
        if (e.key === 'ArrowLeft') {
          e.preventDefault();
          if (viewingIndex > 0) setViewingIndex(viewingIndex - 1);
        }
        if (e.key === 'ArrowRight') {
          e.preventDefault();
          if (viewingIndex < results.length - 1) setViewingIndex(viewingIndex + 1);
        }
        if (e.key === 'Escape') setViewingIndex(-1);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [viewingIndex, results.length]);

  // Save credentials on change
  useEffect(() => {
    localStorage.setItem('pic_serverUrl', serverUrl);
    localStorage.setItem('pic_apiKey', apiKey);
  }, [serverUrl, apiKey]);
  
  const getAssetImgSrc = (asset, full = false) => {
    if (asset.isLocal) {
      const localSize = full ? 'large' : 'preview';
      let url = `${API_BASE}/image?path=${encodeURIComponent(asset.originalPath)}&size=${localSize}`;
      if (asset.rotated) url += `&t=${asset.rotated}`;
      return url;
    }
    // Immich only supports 'thumbnail' and 'preview' size formats
    let url = `${getNormalizedServerUrl()}/api/assets/${asset.id}/thumbnail?size=preview&x-api-key=${apiKey}`;
    if (asset.rotated) url += `&t=${asset.rotated}`;
    return url;
  };
  
  const getNormalizedServerUrl = () => {
    let url = serverUrl.trim().replace(/\/$/, '');
    if (!url) return '';
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'http://' + url;
    }
    return url;
  };
  
  const handleSaveConfig = () => {
    localStorage.setItem('pic_serverUrl', serverUrl);
    localStorage.setItem('pic_apiKey', apiKey);
    setConfigSavedMsg(true);
    setTimeout(() => setConfigSavedMsg(false), 3000);
  };

  const handleTestConnection = async () => {
    if (!serverUrl || !apiKey) return;
    setTestConnMsg('Testing...');
    setError('');
    try {
      const response = await axios.post(`${API_BASE}/test-connection`, {
        server_url: serverUrl,
        api_key: apiKey
      });
      setTestConnMsg(response.data.message || '✓ Success');
    } catch (err) {
      setTestConnMsg('✗ Failed');
      setError(err.response?.data?.detail || err.message);
    }
    setTimeout(() => setTestConnMsg(''), 4000);
  };

  const handleSmartSearch = async (e) => {
    if (e) e.preventDefault();
    if (!serverUrl || !apiKey || !query) return;

    setLoading(true);
    setError('');
    setSelectedPaths(new Set());
    
    try {
      const response = await axios.post(`${API_BASE}/search`, {
        server_url: serverUrl,
        api_key: apiKey,
        query,
        limit: 100
      });
      setResults(response.data.assets || []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const loadPeople = async () => {
    if (!serverUrl || !apiKey) return;
    setLoading(true);
    setError('');
    try {
      const response = await axios.post(`${API_BASE}/people`, {
        server_url: serverUrl,
        api_key: apiKey,
      });
      setPeople(response.data.people || []);
      setResults([]);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadPersonAssets = async (personId) => {
    setLoading(true);
    setError('');
    setSelectedPaths(new Set());
    try {
      const response = await axios.post(`${API_BASE}/people/assets`, {
        server_url: serverUrl,
        api_key: apiKey,
        person_id: personId
      });
      setResults(response.data.assets || []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const loadFolderImages = async (folder) => {
    setLoading(true);
    setError('');
    setSelectedPaths(new Set());
    try {
      const response = await axios.get(`${API_BASE}/folder/images?folder=${encodeURIComponent(folder)}`);
      setResults(response.data.assets || []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleAutoSplit = async () => {
    if (!viewingAsset) return;
    setIsProcessing(true);
    try {
      const response = await axios.post(`${API_BASE}/split`, { path: viewingAsset.originalPath });
      alert(`Successfully split image into ${response.data.parts.length} parts!`);
      if (mode === 'folder') {
        loadFolderImages(selectedFolder);
      }
      setViewingIndex(-1);
    } catch (err) {
      alert(`Split failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleViewerRotate = async () => {
    if (!viewingAsset) return;
    setIsProcessing(true);
    try {
      await axios.post(`${API_BASE}/rotate`, { paths: [viewingAsset.originalPath] });
      setResults(results.map((r, i) => i === viewingIndex ? {...r, rotated: Date.now()} : r));
    } catch (err) {
      alert(`Rotate failed: ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleViewerTrash = async () => {
    if (!viewingAsset) return;
    if (window.confirm("Are you sure you want to trash this image?")) {
      setIsProcessing(true);
      try {
        await axios.post(`${API_BASE}/trash`, { paths: [viewingAsset.originalPath] });
        const newResults = results.filter((_, i) => i !== viewingIndex);
        setResults(newResults);
        if (newResults.length === 0) setViewingIndex(-1);
        else if (viewingIndex >= newResults.length) setViewingIndex(newResults.length - 1);
      } catch (err) {
        alert(`Trash failed: ${err.message}`);
      } finally {
        setIsProcessing(false);
      }
    }
  };

  const handleViewerAddTag = async () => {
    if (!viewingAsset || !tagInput) return;
    setIsProcessing(true);
    try {
      await axios.post(`${API_BASE}/tags`, {
        paths: [viewingAsset.originalPath],
        tag: tagInput,
        action: 'add'
      });
      setViewerTags([...viewerTags, tagInput]);
      setTagInput('');
    } catch (err) {
      alert(`Tagging failed: ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const toggleSelection = (path) => {
    const newSelection = new Set(selectedPaths);
    if (newSelection.has(path)) {
      newSelection.delete(path);
    } else {
      newSelection.add(path);
    }
    setSelectedPaths(newSelection);
  };

  const selectAll = () => {
    if (selectedPaths.size === results.length) {
      setSelectedPaths(new Set());
    } else {
      setSelectedPaths(new Set(results.map(r => r.originalPath)));
    }
  };

  const handleMassAction = async (actionType) => {
    if (selectedPaths.size === 0) return;
    setIsProcessing(true);
    setError('');

    const paths = Array.from(selectedPaths);
    try {
      if (actionType === 'addTag' || actionType === 'removeTag') {
        if (!tagInput) {
          setError('Please enter a tag');
          setIsProcessing(false);
          return;
        }
        await axios.post(`${API_BASE}/tags`, {
          paths,
          tag: tagInput,
          action: actionType === 'addTag' ? 'add' : 'remove'
        });
        alert(`Successfully modified tags for ${paths.length} images`);
      } else if (actionType === 'rotate') {
        await axios.post(`${API_BASE}/rotate`, { paths });
        alert(`Successfully rotated ${paths.length} images`);
      } else if (actionType === 'trash') {
        if (window.confirm(`Are you sure you want to trash ${paths.length} images?`)) {
          await axios.post(`${API_BASE}/trash`, { paths });
          setResults(results.filter(r => !selectedPaths.has(r.originalPath)));
          setSelectedPaths(new Set());
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="app-container">
      <header className="header">
        <h1>PicCurator Web</h1>
        <p>AI Smart Search & Mass Edit</p>
      </header>

      <main>
        <div className="search-panel">
          <form className="search-form" onSubmit={(e) => { e.preventDefault(); if (mode === 'smart') handleSmartSearch(); else loadPeople(); }}>
            <div className="input-group">
              <label>Server URL</label>
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <Server size={18} style={{ position: 'absolute', left: '12px', color: 'var(--text-muted)' }} />
                <input
                  type="url"
                  placeholder="http://192.168.1.100:2283"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                  style={{ paddingLeft: '2.5rem', width: '100%' }}
                  required
                />
              </div>
            </div>
            
            <div className="input-group">
              <label>API Key</label>
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <Key size={18} style={{ position: 'absolute', left: '12px', color: 'var(--text-muted)' }} />
                <input
                  type="password"
                  placeholder="Your Immich API Key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  style={{ paddingLeft: '2.5rem', width: '100%' }}
                  required
                />
              </div>
            </div>

            <div className="input-group full-width" style={{ display: 'flex', flexDirection: 'row', gap: '1rem', marginTop: '1rem' }}>
              <button type="button" className={`btn-action ${mode === 'smart' ? 'btn-primary' : ''}`} onClick={() => { setMode('smart'); setResults([]); }} style={{ flex: 1, justifyContent: 'center', background: mode === 'smart' ? 'var(--primary)' : 'rgba(255,255,255,0.1)' }}>
                <Search size={18} /> Smart Search
              </button>
              <button type="button" className={`btn-action ${mode === 'people' ? 'btn-primary' : ''}`} onClick={() => { setMode('people'); loadPeople(); }} style={{ flex: 1, justifyContent: 'center', background: mode === 'people' ? '#3b82f6' : 'rgba(255,255,255,0.1)' }}>
                <Users size={18} /> People Search
              </button>
              <button type="button" className={`btn-action ${mode === 'folder' ? 'btn-primary' : ''}`} onClick={() => { setMode('folder'); loadFolderImages(selectedFolder); }} style={{ flex: 1, justifyContent: 'center', background: mode === 'folder' ? '#10b981' : 'rgba(255,255,255,0.1)' }}>
                <Folder size={18} /> Local Folders
              </button>
            </div>
            
            <div className="input-group full-width" style={{ display: 'flex', justifyContent: 'center', marginTop: '0.5rem', gap: '1rem' }}>
              <button type="button" className="btn-action" onClick={handleTestConnection} disabled={!serverUrl || !apiKey} style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' }}>
                {testConnMsg || 'Test Connection'}
              </button>
              <button type="button" className="btn-action" onClick={handleSaveConfig} style={{ background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' }}>
                {configSavedMsg ? '✓ Configuration Saved' : 'Save Configuration'}
              </button>
            </div>

            {mode === 'smart' && (
              <>
                <div className="input-group full-width">
                  <label>Smart Search Query</label>
                  <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                    <Search size={18} style={{ position: 'absolute', left: '12px', color: 'var(--text-muted)' }} />
                    <input
                      type="text"
                      placeholder="e.g., A decorated Christmas tree"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      style={{ paddingLeft: '2.5rem', width: '100%' }}
                      required
                    />
                  </div>
                </div>
                <div className="input-group full-width">
                  <button type="submit" className="btn-search" disabled={loading || !serverUrl || !apiKey || !query}>
                    {loading ? <div className="spinner"></div> : <><Search size={20} /> Search Images</>}
                  </button>
                </div>
              </>
            )}

            {mode === 'folder' && (
              <>
                <div className="input-group full-width">
                  <label>Select Folder</label>
                  <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                    <Folder size={18} style={{ position: 'absolute', left: '12px', color: 'var(--text-muted)' }} />
                    <select
                      value={selectedFolder}
                      onChange={(e) => {
                        setSelectedFolder(e.target.value);
                        loadFolderImages(e.target.value);
                      }}
                      style={{ paddingLeft: '2.5rem', width: '100%', padding: '0.75rem', borderRadius: '0.5rem', background: 'rgba(0,0,0,0.2)', color: 'white', border: '1px solid rgba(255,255,255,0.1)' }}
                    >
                      <option value="">(Root folder)</option>
                      {folders.map(f => (
                        <option key={f} value={f}>{f}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="input-group full-width">
                  <button type="button" className="btn-search" onClick={() => loadFolderImages(selectedFolder)} disabled={loading} style={{ background: '#10b981' }}>
                    {loading ? <div className="spinner"></div> : <><Folder size={20} /> Reload Folder</>}
                  </button>
                </div>
              </>
            )}
          </form>

          {error && (
            <div className="error-message">
              <AlertCircle size={20} style={{ display: 'inline', marginRight: '8px', verticalAlign: 'middle' }} />
              {error}
            </div>
          )}
        </div>

        {mode === 'people' && people.length > 0 && results.length === 0 && (
          <div className="results-section">
            <h2>Select a Person</h2>
            <div className="results-grid" style={{ marginTop: '1.5rem' }}>
              {people.map((person) => (
                <div key={person.id} className="asset-card" onClick={() => loadPersonAssets(person.id)}>
                  <div className="asset-img-container" style={{ background: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    {person.thumbnailPath ? (
                      <img 
                        src={`${getNormalizedServerUrl()}/api/people/${person.id}/thumbnail?x-api-key=${apiKey}`}
                        alt={person.name}
                        className="asset-img"
                        onError={(e) => { e.target.style.display='none'; }}
                      />
                    ) : (
                      <User size={64} color="var(--text-muted)" />
                    )}
                  </div>
                  <div className="asset-info" style={{ textAlign: 'center' }}>
                    <strong>{person.name || 'Unknown'}</strong>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {results.length > 0 && (
          <div className="results-section">
            <div className="mass-edit-toolbar">
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <button className="btn-action" onClick={selectAll}>
                  {selectedPaths.size === results.length ? <CheckSquare size={18} /> : <Square size={18} />}
                  Select All
                </button>
                <span>{selectedPaths.size} selected</span>
                {mode === 'people' && <button className="btn-action" onClick={() => setResults([])} style={{ marginLeft: '1rem' }}>← Back to People</button>}
              </div>
              
              <div className="toolbar-actions">
                <div className="tag-input-group">
                  <input 
                    type="text" 
                    placeholder="Enter tag..." 
                    value={tagInput}
                    onChange={e => setTagInput(e.target.value)}
                    style={{ padding: '0.5rem', width: '150px' }}
                  />
                  <button className="btn-action" onClick={() => handleMassAction('addTag')} disabled={isProcessing || selectedPaths.size === 0}>
                    <Tag size={18} /> Add
                  </button>
                  <button className="btn-action" onClick={() => handleMassAction('removeTag')} disabled={isProcessing || selectedPaths.size === 0}>
                    Remove
                  </button>
                </div>
                
                <button className="btn-action" onClick={() => handleMassAction('rotate')} disabled={isProcessing || selectedPaths.size === 0}>
                  <RotateCw size={18} /> Rotate
                </button>
                <button className="btn-action btn-danger" onClick={() => handleMassAction('trash')} disabled={isProcessing || selectedPaths.size === 0}>
                  <Trash2 size={18} /> Trash
                </button>
              </div>
            </div>

            <div className="results-grid">
              {results.map((asset, index) => {
                const isSelected = selectedPaths.has(asset.originalPath);
                return (
                  <div 
                    key={asset.id} 
                    className={`asset-card ${isSelected ? 'selected' : ''}`}
                    onClick={() => toggleSelection(asset.originalPath)}
                    onDoubleClick={() => setViewingIndex(index)}
                  >
                    <div className="checkbox-container">
                      <input 
                        type="checkbox" 
                        checked={isSelected} 
                        readOnly
                      />
                    </div>
                    <div className="asset-img-container">
                      <img 
                        src={getAssetImgSrc(asset, false)}
                        alt={asset.originalFileName}
                        className="asset-img"
                        loading="lazy"
                      />
                    </div>
                    <div className="asset-info">
                      <div className="asset-id" title={asset.originalPath}>
                        {asset.originalFileName}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </main>

      {viewingAsset && (
        <div 
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.95)', zIndex: 100,
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
          }}
          onClick={() => setViewingIndex(-1)}
        >
          <div style={{ position: 'absolute', top: '1rem', right: '1rem', display: 'flex', gap: '1rem', zIndex: 110 }}>
            <button className="btn-action" onClick={(e) => { e.stopPropagation(); handleAutoSplit(); }} disabled={isProcessing} style={{ background: '#3b82f6' }}>
              <Scissors size={18} /> {isProcessing ? 'Processing...' : 'Split Image'}
            </button>
            <button className="btn-action" onClick={() => setViewingIndex(-1)} style={{ background: 'rgba(255,255,255,0.1)' }}>
              <X size={18} /> Close
            </button>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '80vh' }} onClick={e => e.stopPropagation()}>
            {viewingIndex > 0 && (
              <button 
                className="btn-action" 
                onClick={(e) => { e.stopPropagation(); setViewingIndex(viewingIndex - 1); }} 
                style={{ position: 'absolute', left: '1rem', padding: '1rem', borderRadius: '50%', zIndex: 110 }}
              >
                <ChevronLeft size={32} />
              </button>
            )}
            
            <img 
              src={getAssetImgSrc(viewingAsset, true)}
              style={{ maxHeight: '100%', maxWidth: '80vw', objectFit: 'contain' }}
              alt={viewingAsset.originalFileName}
            />
            
            {viewingIndex < results.length - 1 && (
              <button 
                className="btn-action" 
                onClick={(e) => { e.stopPropagation(); setViewingIndex(viewingIndex + 1); }} 
                style={{ position: 'absolute', right: '1rem', padding: '1rem', borderRadius: '50%', zIndex: 110 }}
              >
                <ChevronRight size={32} />
              </button>
            )}
          </div>
          
          <div style={{ color: 'white', marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'center', background: 'rgba(0,0,0,0.8)', padding: '1rem', borderRadius: '0.5rem', zIndex: 110, width: '80vw' }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
              <div style={{ fontSize: '0.9rem', color: '#94a3b8' }}>
                {viewingIndex + 1} of {results.length} - {viewingAsset.originalPath}
              </div>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <button className="btn-action" onClick={handleViewerRotate} disabled={isProcessing}>
                  <RotateCw size={18} /> Rotate
                </button>
                <button className="btn-action btn-danger" onClick={handleViewerTrash} disabled={isProcessing}>
                  <Trash2 size={18} /> Trash
                </button>
              </div>
            </div>
            <div style={{ display: 'flex', width: '100%', gap: '1rem', alignItems: 'center', marginTop: '0.5rem' }}>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', flex: 1 }}>
                {viewerTags.length === 0 ? <span style={{ color: '#64748b', fontSize: '0.9rem' }}>No tags</span> : null}
                {viewerTags.map((t, i) => (
                  <span key={i} style={{ background: '#3b82f6', padding: '0.2rem 0.5rem', borderRadius: '0.25rem', fontSize: '0.85rem' }}>
                    {t}
                  </span>
                ))}
              </div>
              <div className="tag-input-group">
                <input 
                  type="text" 
                  placeholder="Add a new tag..." 
                  value={tagInput}
                  onChange={e => setTagInput(e.target.value)}
                  style={{ padding: '0.5rem', width: '200px' }}
                />
                <button className="btn-action" onClick={handleViewerAddTag} disabled={isProcessing || !tagInput}>
                  <Tag size={18} /> Add Tag
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
