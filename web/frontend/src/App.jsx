import { useState, useEffect } from 'react';
import axios from 'axios';
import { Search, Server, Key, AlertCircle, Trash2, RotateCw, Tag, CheckSquare, Square, Users, User } from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

function App() {
  const [serverUrl, setServerUrl] = useState(() => localStorage.getItem('pic_serverUrl') || '');
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('pic_apiKey') || '');
  const [mode, setMode] = useState('smart'); // 'smart' or 'people'
  
  const [query, setQuery] = useState('');
  const [people, setPeople] = useState([]);
  
  const [configSavedMsg, setConfigSavedMsg] = useState(false);
  
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [error, setError] = useState('');
  
  // Mass Edit State
  const [selectedPaths, setSelectedPaths] = useState(new Set());
  const [tagInput, setTagInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  
  // Image Viewer State
  const [viewingAsset, setViewingAsset] = useState(null);

  // Save credentials on change
  useEffect(() => {
    localStorage.setItem('pic_serverUrl', serverUrl);
    localStorage.setItem('pic_apiKey', apiKey);
  }, [serverUrl, apiKey]);
  
  const handleSaveConfig = () => {
    localStorage.setItem('pic_serverUrl', serverUrl);
    localStorage.setItem('pic_apiKey', apiKey);
    setConfigSavedMsg(true);
    setTimeout(() => setConfigSavedMsg(false), 3000);
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
              <button type="button" className={`btn-action ${mode === 'smart' ? 'btn-primary' : ''}`} onClick={() => setMode('smart')} style={{ flex: 1, justifyContent: 'center', background: mode === 'smart' ? 'var(--primary)' : 'rgba(255,255,255,0.1)' }}>
                <Search size={18} /> Smart Search
              </button>
              <button type="button" className={`btn-action ${mode === 'people' ? 'btn-primary' : ''}`} onClick={() => { setMode('people'); loadPeople(); }} style={{ flex: 1, justifyContent: 'center', background: mode === 'people' ? '#3b82f6' : 'rgba(255,255,255,0.1)' }}>
                <Users size={18} /> People Search
              </button>
            </div>
            
            <div className="input-group full-width" style={{ display: 'flex', justifyContent: 'center', marginTop: '0.5rem' }}>
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
                        src={`${serverUrl.replace(/\/$/, '')}/api/people/${person.id}/thumbnail?x-api-key=${apiKey}`}
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
                    onDoubleClick={() => setViewingAsset(asset)}
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
                        src={`${serverUrl.replace(/\/$/, '')}/api/assets/${asset.id}/thumbnail?size=preview&x-api-key=${apiKey}`}
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
            backgroundColor: 'rgba(0,0,0,0.9)', zIndex: 100,
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'
          }}
          onClick={() => setViewingAsset(null)}
        >
          <img 
            src={`${serverUrl.replace(/\/$/, '')}/api/assets/${viewingAsset.id}/thumbnail?size=preview&x-api-key=${apiKey}`}
            style={{ maxHeight: '90vh', maxWidth: '90vw', objectFit: 'contain' }}
            alt={viewingAsset.originalFileName}
          />
          <div style={{ color: 'white', marginTop: '1rem', background: 'rgba(0,0,0,0.5)', padding: '0.5rem 1rem', borderRadius: '0.5rem' }}>
            {viewingAsset.originalPath}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
