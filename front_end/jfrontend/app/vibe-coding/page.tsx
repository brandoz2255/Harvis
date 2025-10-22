import UnderConstruction from '@/components/UnderConstruction';

export default function VibeCodingPage() {
  return (
    <UnderConstruction
      pageName="Vibe Coding"
      description="AI-powered development environment with isolated containers for each project. Code with AI assistance in real-time!"
      expectedFeatures={[
        "Interactive Code Editor with Monaco",
        "AI-Powered Code Assistant",
        "Docker Container Integration",
        "Real-time Terminal Access",
        "File System Explorer",
        "Voice Command Support"
      ]}
    />
  );
}
