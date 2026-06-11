**AI Log communication Clarifications:**

Since this is for **NDIS participant ↔ support worker communications**, the safest approach is to align analysis with participant wellbeing, safeguarding, duty of care, service quality, and communication effectiveness rather than attempting clinical diagnosis.

### **1\. Do I need to classify every sentiment? (happy, sad, angry...)**

Not necessarily. For NDIS-related conversations, it may be more valuable to classify communications into broader wellbeing and engagement categories rather than an extensive emotional taxonomy.  
Example categories:

* Positive / Satisfied  
* Neutral  
* Frustrated / Dissatisfied  
* Distressed / Upset  
* Confused / Uncertain  
* Engaged  
* Disengaged

The goal should be identifying participant wellbeing and service concerns rather than detecting every possible emotion.

### **2\. Will every sentiment get sent in real time?**

This depends on the intended workflow.  
A common approach would be:

* Analyze messages in real time as they are exchanged.  
* Generate sentiment updates continuously.  
* Trigger alerts only when predefined thresholds are met (e.g., repeated frustration, distress, escalation, safeguarding concerns, disengagement).

Sending every sentiment event may create excessive noise, so exception-based notifications are usually more practical.  
 

### **3\. How do we define risk? Is there any specific list to call that conversation as risk?**

For NDIS communications, risk could include indicators such as:

* Participants expressing distress, anxiety, fear, or emotional crisis.  
* Mentions of self-harm, harm to others, or safety concerns.  
* Abuse, neglect, exploitation, or safeguarding concerns.  
* Repeated complaints about service delivery.  
* Missed supports impacting participant wellbeing.  
* Escalating conflict between participant and support worker.  
* Medical or emergency situations requiring urgent attention.  
* Participants repeatedly indicate they are not receiving required support.

Risk levels could be categorized as:

* Low Risk  
* Medium Risk  
* High Risk  
* Critical / Immediate Attention Required

 

### **4\. Same for breakdown. Will the "breakdown" have specific requirements or be general?**

Communication breakdown should ideally have defined criteria.  
Examples:

* Questions repeatedly unanswered.  
* Participant requests ignored or misunderstood.  
* Repeated clarification requests.  
* Conflicting information provided.  
* Conversations becoming circular without resolution.  
* Escalating frustration due to miscommunication.  
* Failure to agree on next steps.

The system can either:

* Use generic communication breakdown detection, or  
* Follow a client-defined set of breakdown rules.

 

### **5\. Can you explain more about the scope of full conversation analysis?**

A comprehensive conversation analysis could include:

* Overall sentiment trend.  
* Participant engagement level.  
* Support worker responsiveness.  
* Communication quality assessment.  
* Key discussion topics.  
* Action items and commitments.  
* Risk and safeguarding indicators.  
* Escalation detection.  
* Communication breakdown identification.  
* Resolution status.  
* Participant satisfaction indicators.  
* Conversation summary.  
* Recommended follow-up actions.

 

### **6\. Some examples, if possible.**

### **Example 1 – Low Risk**

**Participant:** "I haven't received my transport support this week."  
**Support Worker:** "Sorry about that. I'll check and get back to you today."  
**Analysis:**

* Sentiment: Mild frustration  
* Risk: Low  
* Breakdown: No  
* Outcome: Resolved

---

### **Example 2 – Communication Breakdown**

**Participant:** "Can you explain why my support hours changed?"  
**Support Worker:** "Please check your plan."  
**Participant:** "I already did, but I don't understand."  
**Support Worker:** "It's in the documents."  
**Analysis:**

* Sentiment: Frustrated  
* Risk: Medium  
* Breakdown: Yes  
* Reason: Participant's question not adequately addressed

---

### **Example 3 – High Risk**

**Participant:** "I'm feeling overwhelmed and don't know how I'll manage without support this week."  
**Support Worker:** "I'll notify the coordinator immediately."  
**Analysis:**

* Sentiment: Distressed  
* Risk: High  
* Breakdown: No  
* Recommended Action: Escalate to coordinator for review

