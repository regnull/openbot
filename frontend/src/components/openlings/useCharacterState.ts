import { useEffect, useState } from "react";
import type { CharacterState, OpenlingCharacter } from "./runtime/OpenlingCharacter";

/** Live state of one character; re-renders when it changes. */
export function useCharacterState(character: OpenlingCharacter | null): CharacterState | null {
  const [state, setState] = useState<CharacterState | null>(character?.state ?? null);
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    setState(character?.state ?? null);
    if (!character) return;
    return character.onChange(() => setState(character.state));
  }, [character]);
  return state;
}
