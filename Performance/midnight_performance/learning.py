"""Deterministic active-learning selection and non-collapsing outcome labels."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class QuestionCandidate:
    prompt_run_id:str; uncertainty:float; novelty:float; disagreement:float; information_gain:float
    @property
    def score(self)->float: return round((self.uncertainty+self.novelty+self.disagreement+self.information_gain)/4,3)
def select_question(candidates:tuple[QuestionCandidate,...], threshold:float=.5)->QuestionCandidate|None:
    eligible=[x for x in candidates if x.score>=threshold]
    return max(eligible,key=lambda x:x.score) if eligible else None
@dataclass(frozen=True, slots=True)
class MultiSignalLabel:
    version:str; user_signal:str|None; execution_signal:str|None; code_signal:str|None; watch_signal:str|None
    @property
    def disagreement(self)->bool:
        values={x for x in (self.user_signal,self.execution_signal,self.code_signal,self.watch_signal) if x is not None}
        return len(values)>1
