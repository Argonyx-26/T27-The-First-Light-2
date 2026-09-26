import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import './NimbusHero.css';

const tabContents = {
  cli: {
    command: "$ nimbus pool create --name web-db-test",
    flags: [
      { key: "--tier", val: "encrypted-fast" },
      { key: "--quota", val: "8TiB" },
      { key: "--region", val: "us-east-1" },
    ],
    status: "✓ Pool created successfully (id: pool_928af1)"
  },
  api: {
    method: "POST",
    path: "/v1/storage/pools",
    body: {
      name: "web-db-test",
      tier: "encrypted-fast",
      quota: "8 TiB"
    },
    status: "202 accepted"
  },
  console: {
    title: "STORAGE",
    subtitle: "/ Pool Overview",
    fields: [
      { label: "Status:", value: "Active • High Availability", color: "#4ade80" },
      { label: "Allocated:", value: "8 TiB NVMe" },
      { label: "Encryption:", value: "AES-256-GCM Hardware" }
    ],
    status: "Telemetry synced 1s ago"
  }
};

export default function NimbusHero() {
  const mountRef = useRef(null);
  const cardRef = useRef(null);
  const [activeTab, setActiveTab] = useState('api');

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || window.innerWidth;
    let height = container.clientHeight || window.innerHeight;

    // Scene, Camera, Renderer
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x07090e, 0.045);

    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
    camera.position.set(0, 0, 15);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance"
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    container.appendChild(renderer.domElement);

    // Warm Amber Core PointLight
    const amberLight = new THREE.PointLight(0xffa733, 4.5, 35);
    amberLight.position.set(1, 4, 6);
    scene.add(amberLight);

    // Cool Slate Blue Ambient/Back Light
    const coolLight = new THREE.PointLight(0x2563eb, 2.2, 40);
    coolLight.position.set(10, -4, 4);
    scene.add(coolLight);

    const ambientLight = new THREE.AmbientLight(0x0b1120, 1.8);
    scene.add(ambientLight);

    // 3D Organic Undulating Wireframe Plane
    const planeGeo = new THREE.PlaneGeometry(35, 24, 60, 45);
    const posAttr = planeGeo.attributes.position;
    const originalPositions = new Float32Array(posAttr.array);

    const planeMat = new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      wireframe: true,
      roughness: 0.4,
      metalness: 0.8,
      transparent: true,
      opacity: 0.22
    });

    const gridPlane = new THREE.Mesh(planeGeo, planeMat);
    gridPlane.rotation.x = -Math.PI / 3.2;
    gridPlane.rotation.z = -0.15;
    gridPlane.position.set(2, -4, -2);
    scene.add(gridPlane);

    // 3D Abstract Geometric Form on the right
    const formGeo = new THREE.TorusKnotGeometry(4.2, 1.3, 120, 24, 2, 3);
    const formMat = new THREE.MeshStandardMaterial({
      color: 0x111928,
      roughness: 0.25,
      metalness: 0.85,
      flatShading: true,
    });

    const abstractForm = new THREE.Mesh(formGeo, formMat);
    abstractForm.position.set(8.5, 0.5, -4);
    abstractForm.scale.set(1.1, 1.1, 1.1);
    scene.add(abstractForm);

    const formWireMat = new THREE.MeshBasicMaterial({
      color: 0x475569,
      wireframe: true,
      transparent: true,
      opacity: 0.18
    });
    const abstractFormWire = new THREE.Mesh(formGeo, formWireMat);
    abstractForm.add(abstractFormWire);

    // Floating Particles
    const particleCount = 280;
    const particleGeo = new THREE.BufferGeometry();
    const particlePos = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount; i++) {
      particlePos[i * 3 + 0] = (Math.random() - 0.5) * 30;
      particlePos[i * 3 + 1] = (Math.random() - 0.5) * 20;
      particlePos[i * 3 + 2] = (Math.random() - 0.5) * 15 - 2;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePos, 3));
    const particleMat = new THREE.PointsMaterial({
      color: 0xf59e0b,
      size: 0.08,
      transparent: true,
      opacity: 0.5,
      blending: THREE.AdditiveBlending
    });

    const particleSystem = new THREE.Points(particleGeo, particleMat);
    scene.add(particleSystem);

    let mouseX = 0;
    let mouseY = 0;
    let targetX = 0;
    let targetY = 0;

    const handleMouseMove = (e) => {
      mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
      mouseY = (e.clientY / window.innerHeight - 0.5) * 2;

      if (cardRef.current) {
        const rect = cardRef.current.getBoundingClientRect();
        const cardCenterX = rect.left + rect.width / 2;
        const cardCenterY = rect.top + rect.height / 2;
        const dx = (e.clientX - cardCenterX) / 40;
        const dy = (e.clientY - cardCenterY) / 40;
        cardRef.current.style.transform = `perspective(1000px) rotateY(${Math.min(Math.max(dx, -6), 6)}deg) rotateX(${Math.min(Math.max(-dy, -6), 6)}deg)`;
      }
    };

    const handleResize = () => {
      if (!container) return;
      const w = window.innerWidth;
      const h = window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('resize', handleResize);

    const clock = new THREE.Clock();
    let animId;

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const elapsedTime = clock.getElapsedTime();

      // Wave plane
      const pos = planeGeo.attributes.position;
      for (let i = 0; i < pos.count; i++) {
        const u = originalPositions[i * 3 + 0];
        const v = originalPositions[i * 3 + 1];
        pos.array[i * 3 + 2] =
          Math.sin(u * 0.3 + elapsedTime * 0.6) * 0.8 +
          Math.cos(v * 0.4 + elapsedTime * 0.4) * 0.6;
      }
      pos.needsUpdate = true;

      // Abstract form rotation
      abstractForm.rotation.x = elapsedTime * 0.08;
      abstractForm.rotation.y = elapsedTime * 0.12;
      abstractForm.position.y = 0.5 + Math.sin(elapsedTime * 0.5) * 0.3;

      // Particle rotation
      particleSystem.rotation.y = elapsedTime * 0.02;

      // Parallax
      targetX += (mouseX * 0.8 - targetX) * 0.04;
      targetY += (-mouseY * 0.5 - targetY) * 0.04;
      camera.position.x = targetX;
      camera.position.y = targetY;
      camera.lookAt(1, 0, 0);

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      renderer.dispose();
    };
  }, []);

  return (
    <div className="nimbus-hero-root">
      {/* 3D WebGL Canvas Layer */}
      <div className="webgl-canvas-container" ref={mountRef} />

      {/* Atmospheric Vignette & Grid */}
      <div className="bg-ambience" />
      <div className="grid-overlay" />

      {/* Foreground Hero UI */}
      <main className="hero-wrapper">
        <header className="nav-bar">
          <div className="brand-badge">NIMBUS GRID</div>
          <nav className="nav-links">
            <a href="#technology" className="nav-item">TECHNOLOGY</a>
            <a href="#security" className="nav-item">SECURITY</a>
            <a href="#capacity" className="nav-item">CAPACITY</a>
            <a href="#operations" className="nav-item">OPERATIONS</a>
          </nav>
          <a href="#get-started" className="cta-btn">GET STARTED</a>
        </header>

        <section className="card-section">
          <div className="code-card" ref={cardRef}>
            <div className="card-header">
              <div className="tab-group">
                <button
                  className={`tab-btn ${activeTab === 'cli' ? 'active' : ''}`}
                  onClick={() => setActiveTab('cli')}
                >
                  CLI
                </button>
                <button
                  className={`tab-btn ${activeTab === 'api' ? 'active' : ''}`}
                  onClick={() => setActiveTab('api')}
                >
                  API
                </button>
                <button
                  className={`tab-btn ${activeTab === 'console' ? 'active' : ''}`}
                  onClick={() => setActiveTab('console')}
                >
                  CONSOLE
                </button>
              </div>
              <div className="status-indicator">
                <div className="indicator-bar" />
                <div className="indicator-dot" />
              </div>
            </div>

            <div className="card-body">
              {activeTab === 'api' && (
                <>
                  <div className="code-line">
                    <span className="http-method">POST</span>{" "}
                    <span className="endpoint-path">/v1/storage/pools</span>
                  </div>
                  <div className="code-spacer" />
                  <div className="code-line"><span className="json-bracket">&#123;</span></div>
                  <div className="code-line">
                    {"  "}<span className="json-key">"name":</span>{" "}
                    <span className="json-val">"web-db-test"</span>,
                  </div>
                  <div className="code-line">
                    {"  "}<span className="json-key">"tier":</span>{" "}
                    <span className="json-val">"encrypted-fast"</span>,
                  </div>
                  <div className="code-line">
                    {"  "}<span className="json-key">"quota":</span>{" "}
                    <span className="json-val">"8 TiB"</span>
                  </div>
                  <div className="code-line"><span className="json-bracket">&#125;</span></div>
                  <div className="code-spacer" />
                  <div className="status-line">202 accepted</div>
                </>
              )}

              {activeTab === 'cli' && (
                <>
                  <div className="code-line">
                    <span className="http-method">$</span>{" "}
                    <span className="endpoint-path">nimbus pool create --name web-db-test</span>
                  </div>
                  <div className="code-spacer" />
                  <div className="code-line"><span className="json-key">--tier</span> <span className="json-val">encrypted-fast</span></div>
                  <div className="code-line"><span className="json-key">--quota</span> <span className="json-val">8TiB</span></div>
                  <div className="code-line"><span className="json-key">--region</span> <span className="json-val">us-east-1</span></div>
                  <div className="code-spacer" />
                  <div className="status-line">✓ Pool created successfully (id: pool_928af1)</div>
                </>
              )}

              {activeTab === 'console' && (
                <>
                  <div className="code-line">
                    <span className="http-method">STORAGE</span>{" "}
                    <span className="endpoint-path">/ Pool Overview</span>
                  </div>
                  <div className="code-spacer" />
                  <div className="code-line"><span className="json-key">Status:</span> <span className="json-val" style={{ color: '#4ade80' }}>Active • High Availability</span></div>
                  <div className="code-line"><span className="json-key">Allocated:</span> <span className="json-val">8 TiB NVMe</span></div>
                  <div className="code-line"><span className="json-key">Encryption:</span> <span className="json-val">AES-256-GCM Hardware</span></div>
                  <div className="code-spacer" />
                  <div className="status-line">Telemetry synced 1s ago</div>
                </>
              )}
            </div>
          </div>
        </section>

        <footer className="hero-footer">
          <h1 className="hero-title">
            <span>Cloud space that scales</span>
            <span>with your business</span>
            <span>systems.</span>
          </h1>
          <p className="hero-subtitle">
            Nimbus Grid sells secure cloud storage capacity for companies that need fast onboarding, predictable throughput, encrypted collaboration, and modern data residency controls.
          </p>
        </footer>
      </main>
    </div>
  );
}
