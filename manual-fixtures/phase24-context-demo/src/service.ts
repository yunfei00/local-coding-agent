export interface DemoUser {
  id: string;
  name: string;
}

export function loadDemoUser(): DemoUser {
  return { id: "phase24", name: "Context Demo" };
}
