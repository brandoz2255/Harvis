'use client';
import { useEffect, useRef, useMemo, memo } from "react";
import { Renderer, Program, Mesh, Color, Triangle } from "ogl";

const VERT = `#version 300 es
in vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

// Simplified and more robust fragment shader
const FRAG = `#version 300 es
precision highp float;

uniform float uTime;
uniform float uAmplitude;
uniform vec3 uColorStops[3];
uniform vec2 uResolution;
uniform float uBlend;

out vec4 fragColor;

// Simplex noise function (as provided by the user)
vec3 permute(vec3 x) {
  return mod(((x * 34.0) + 1.0) * x, 289.0);
}

float snoise(vec2 v){
  const vec4 C = vec4(
      0.211324865405187, 0.366025403784439,
      -0.577350269189626, 0.024390243902439
  );
  vec2 i  = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);

  vec3 p = permute(
      permute(i.y + vec3(0.0, i1.y, 1.0))
    + i.x + vec3(0.0, i1.x, 1.0)
  );

  vec3 m = max(
      0.5 - vec3(
          dot(x0, x0),
          dot(x12.xy, x12.xy),
          dot(x12.zw, x12.zw)
      ), 
      0.0
  );
  m = m * m;
  m = m * m;

  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);

  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  
  // Simplified color ramp logic
  vec3 rampColor;
  float t = uv.x * 2.0;
  if (t < 1.0) {
    rampColor = mix(uColorStops[0], uColorStops[1], t);
  } else {
    rampColor = mix(uColorStops[1], uColorStops[2], t - 1.0);
  }
  
  float height = snoise(vec2(uv.x * 2.0 + uTime * 0.1, uTime * 0.25)) * 0.5 * uAmplitude;
  height = exp(height);
  height = (uv.y * 2.0 - height + 0.2);
  float intensity = 0.6 * height;
  
  float midPoint = 0.20;
  float auroraAlpha = smoothstep(midPoint - uBlend * 0.5, midPoint + uBlend * 0.5, intensity);
  
  vec3 auroraColor = intensity * rampColor;
  
  fragColor = vec4(auroraColor * auroraAlpha, auroraAlpha);
}
`;

interface AuroraProps {
  className?: string; // Allow className to be passed
  colorStops?: string[];
  amplitude?: number;
  blend?: number;
  time?: number;
  speed?: number;
}

// Add className to props to allow styling from parent
function Aurora(props: AuroraProps) {
  const {
    className,
    colorStops = ["#5227FF", "#7cff67", "#5227FF"],
    amplitude = 1.0,
    blend = 0.5,
    speed = 1.0,
  } = props;

  const ctnDom = useRef<HTMLDivElement>(null);
  // Track if component is mounted to prevent rendering after cleanup
  const isMountedRef = useRef(true);

  // Memoize color stops array to prevent recreation on every render
  const memoizedColorStops = useMemo(() => {
    return colorStops.map((hex) => {
      const c = new Color(hex);
      return [c.r, c.g, c.b];
    });
  }, [colorStops]);

  // Memoize props to prevent WebGL context recreation
  const stableProps = useMemo(() => ({
    amplitude,
    blend,
    speed,
    colorStops: memoizedColorStops
  }), [amplitude, blend, speed, memoizedColorStops]);

  useEffect(() => {
    const ctn = ctnDom.current;
    if (!ctn) return;

    // Reset mounted flag
    isMountedRef.current = true;

    // Check if WebGL is available
    const testCanvas = document.createElement('canvas');
    const testGl = testCanvas.getContext('webgl2') || testCanvas.getContext('webgl');
    if (!testGl) {
      console.warn('WebGL not available, Aurora effect disabled');
      return;
    }

    let renderer: Renderer;
    let gl: WebGL2RenderingContext | WebGLRenderingContext;
    let program: Program | undefined;
    let mesh: Mesh;
    let animateId = 0;

    try {
      renderer = new Renderer({
        alpha: true,
        premultipliedAlpha: true,
        antialias: true,
      });
      gl = renderer.gl;
      
      if (!gl) {
        console.warn('Failed to get WebGL context');
        return;
      }

      gl.clearColor(0, 0, 0, 0);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.canvas.style.backgroundColor = "transparent";

      function resize() {
        if (!ctn || !isMountedRef.current || !renderer || !gl) return;
        const width = ctn.offsetWidth;
        const height = ctn.offsetHeight;

        // Only resize if dimensions actually changed to prevent unnecessary operations
        const currentSize = program?.uniforms?.uResolution?.value;
        if (currentSize && currentSize[0] === width && currentSize[1] === height) {
          return;
        }

        try {
          renderer.setSize(width, height);
          if (program) {
            program.uniforms.uResolution.value = [width, height];
          }
        } catch (e) {
          // Ignore resize errors during cleanup
        }
      }

      // Use passive listener for better performance
      window.addEventListener("resize", resize, { passive: true });

      const geometry = new Triangle(gl);
      if ((geometry.attributes as any).uv) {
        delete (geometry.attributes as any).uv;
      }

      program = new Program(gl, {
        vertex: VERT,
        fragment: FRAG,
        uniforms: {
          uTime: { value: 0 },
          uAmplitude: { value: stableProps.amplitude },
          uColorStops: { value: stableProps.colorStops },
          uResolution: { value: [ctn.offsetWidth, ctn.offsetHeight] },
          uBlend: { value: stableProps.blend },
        },
      });

      mesh = new Mesh(gl, { geometry, program });
      ctn.appendChild(gl.canvas);

      const update = (t: number) => {
        // Check if still mounted before rendering
        if (!isMountedRef.current || !program || !renderer || !gl) {
          return;
        }

        animateId = requestAnimationFrame(update);
        
        try {
          const time = props.time ?? t * 0.01;
          program.uniforms.uTime.value = time * stableProps.speed * 0.1;
          program.uniforms.uAmplitude.value = stableProps.amplitude;
          program.uniforms.uBlend.value = stableProps.blend;
          program.uniforms.uColorStops.value = stableProps.colorStops;
          renderer.render({ scene: mesh });
        } catch (e) {
          // Silently handle render errors during cleanup
          cancelAnimationFrame(animateId);
        }
      };
      animateId = requestAnimationFrame(update);

      resize();

      return () => {
        // Mark as unmounted first to stop any pending renders
        isMountedRef.current = false;
        
        // Cancel animation frame
        cancelAnimationFrame(animateId);
        
        // Remove resize listener
        window.removeEventListener("resize", resize);
        
        // Clean up DOM
        try {
          if (ctn && gl && gl.canvas && gl.canvas.parentNode === ctn) {
            ctn.removeChild(gl.canvas);
          }
        } catch (e) {
          // Ignore DOM cleanup errors
        }
        
        // Properly dispose of WebGL context
        try {
          const loseContext = gl?.getExtension?.("WEBGL_lose_context");
          if (loseContext) {
            loseContext.loseContext();
          }
        } catch (e) {
          // Ignore WebGL cleanup errors
        }
      };
    } catch (e) {
      console.warn('Aurora WebGL initialization failed:', e);
      return;
    }
  }, [stableProps, props.time]); // Only re-create WebGL context when stable props actually change

  // Pass className to the container div
  return <div ref={ctnDom} className={`w-full h-full ${className || ''}`} />;
}

// Memoize the component with a custom comparison function
export default memo(Aurora, (prevProps, nextProps) => {
  // Only re-render if meaningful props have changed
  return (
    prevProps.className === nextProps.className &&
    prevProps.amplitude === nextProps.amplitude &&
    prevProps.blend === nextProps.blend &&
    prevProps.speed === nextProps.speed &&
    prevProps.time === nextProps.time &&
    JSON.stringify(prevProps.colorStops) === JSON.stringify(nextProps.colorStops)
  );
});
