import { createContext, useContext } from "react";
import type { Student } from "./api";

export const StudentContext = createContext<Student | null>(null);

export function useStudent(): Student {
  const s = useContext(StudentContext);
  if (!s) throw new Error("useStudent used outside a selected student");
  return s;
}
