import React from 'react';
import { Folder, Search, TagOff } from 'lucide-react';

export default function MobileGrid({
  results,
  folders,
  selectedFolder,
  setSelectedFolder,
  loadFolderImages,
  onImageClick,
  getAssetImgSrc,
  loading,
  error,
  query,
  setQuery,
  handleSmartSearch,
  handleUntaggedSearch,
  logo
}) {
  return (
    <div style={{ padding: '8px', backgroundColor: '#0f172a', minHeight: '100vh', color: 'white' }}>
      
      {/* Sticky Header / Filter */}
      <div style={{ 
        position: 'sticky', 
        top: 0, 
        backgroundColor: 'rgba(15, 23, 42, 0.95)', 
        backdropFilter: 'blur(10px)',
        zIndex: 10, 
        paddingTop: '8px',
        paddingBottom: '16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px'
      }}>
        {/* Header Title / Logo */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '4px 0' }}>
          {logo && <img src={logo} alt="Logo" style={{ width: '28px', height: '28px', objectFit: 'contain' }} />}
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 'bold', color: '#f8fafc', letterSpacing: '0.5px' }}>PicCurator</h1>
        </div>

        {/* Smart Search Bar */}
        <form onSubmit={handleSmartSearch} style={{ 
          display: 'flex', 
          alignItems: 'center', 
          backgroundColor: '#1e293b', 
          padding: '12px', 
          borderRadius: '16px',
          border: '1px solid rgba(255,255,255,0.05)'
        }}>
           <Search size={20} style={{ marginRight: '12px', color: '#60a5fa' }} />
           <input 
             type="text"
             placeholder="Smart Search (e.g., 'dogs', 'beach')"
             value={query || ''}
             onChange={(e) => setQuery(e.target.value)}
             style={{ 
               flex: 1, 
               backgroundColor: 'transparent', 
               border: 'none', 
               color: 'white', 
               outline: 'none', 
               fontSize: '16px'
             }}
           />
           {query && (
             <button type="submit" disabled={loading} style={{ backgroundColor: '#3b82f6', color: 'white', border: 'none', padding: '6px 12px', borderRadius: '8px', fontWeight: 'bold', opacity: loading ? 0.5 : 1 }}>
               Go
             </button>
           )}
        </form>

        {/* Untagged Photos Button */}
        <button 
          onClick={handleUntaggedSearch}
          disabled={loading}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'rgba(245, 158, 11, 0.2)',
            color: '#fcd34d',
            padding: '12px',
            borderRadius: '16px',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            fontSize: '16px',
            fontWeight: '600',
            opacity: loading ? 0.5 : 1
          }}
        >
          <TagOff size={20} style={{ marginRight: '8px' }} />
          Untagged Photos
        </button>

        {/* Local Folder Dropdown */}
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          backgroundColor: '#1e293b', 
          padding: '12px', 
          borderRadius: '16px' 
        }}>
           <Folder size={20} style={{ marginRight: '12px', color: '#94a3b8' }} />
           <select 
             value={selectedFolder}
             onChange={(e) => {
               setSelectedFolder(e.target.value);
               loadFolderImages(e.target.value);
             }}
             style={{ 
               flex: 1, 
               backgroundColor: 'transparent', 
               border: 'none', 
               color: 'white', 
               outline: 'none', 
               fontSize: '16px',
               appearance: 'none'
             }}
           >
             <option value="">Select Local Folder...</option>
             {folders.map(f => <option key={f} value={f}>{f}</option>)}
           </select>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div style={{ padding: '1rem', color: '#ef4444', textAlign: 'center' }}>
          {error}
        </div>
      )}

      {/* Grid */}
      {loading ? (
        <div style={{ textAlign: 'center', marginTop: '50px', color: '#94a3b8' }}>Loading images...</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px' }}>
          {results.map((asset, index) => (
            <div 
              key={asset.id || index} 
              onClick={() => onImageClick(index)}
              style={{ 
                aspectRatio: '1/1', 
                overflow: 'hidden', 
                borderRadius: '8px', 
                backgroundColor: '#1e293b' 
              }}
            >
              <img 
                src={getAssetImgSrc(asset, false)} 
                alt={asset.originalFileName}
                loading="lazy"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />
            </div>
          ))}
          
          {results.length === 0 && !loading && (
             <div style={{ gridColumn: 'span 3', textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>
               No images found in this folder.
             </div>
          )}
        </div>
      )}
    </div>
  );
}
