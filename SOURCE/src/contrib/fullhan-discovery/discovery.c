/* Small read-only ONVIF discovery responder. Project MIT license.
 * No filesystem writes, command execution, incoming URLs or XML entities. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <net/if.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define PACKET_MAX 8192
#define DISCOVERY "http://schemas.xmlsoap.org/ws/2005/04/discovery"
#define ADDRESSING "http://schemas.xmlsoap.org/ws/2004/08/addressing"
#define SOAP "http://www.w3.org/2003/05/soap-envelope"
#define NETWORK "http://www.onvif.org/ver10/network/wsdl"
#define DEVICE "http://www.onvif.org/ver10/device/wsdl"
static volatile sig_atomic_t stopping;
static unsigned instance_id = 1;
static uint64_t message_nonce;
static void stop_signal(int signum) { (void)signum; stopping = 1; }

static int uuid_valid(const char *text) {
    size_t i;
    if (strlen(text) != 36) return 0;
    for (i = 0; i < 36; ++i) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (text[i] != '-') return 0;
        } else if (!isxdigit((unsigned char)text[i])) return 0;
    }
    return 1;
}

/* Bounded XML subset for discovery envelopes. Namespace bindings are immutable
 * scope chains, so child rebindings cannot affect siblings or QName values.
 * No DTD, entities, comments, processing instructions, or external resources. */
#define XML_NODES 128
#define XML_DEPTH 24
#define XML_BINDINGS 128
#define XML_ATTRIBUTES 16
struct span { const char *p; size_t n; };
struct binding { struct span prefix, uri; int previous; };
struct node {
    struct span qname, local, uri, content, match_by;
    int scope, first, last, next, text;
};
struct document {
    struct node nodes[XML_NODES]; struct binding bindings[XML_BINDINGS];
    unsigned count, binding_count;
};
struct attribute { struct span prefix, local, value; int declaration; };
static int same(struct span a, struct span b) {
    return a.n == b.n && (!a.n || !memcmp(a.p, b.p, a.n));
}
static int literal(struct span a, const char *s) {
    return a.n == strlen(s) && (!a.n || !memcmp(a.p, s, a.n));
}
static int name_start(unsigned char c) { return isalpha(c) || c == '_'; }
static int name_char(unsigned char c) { return isalnum(c) || c == '_' || c == '-' || c == '.'; }
static int qname(const char **cursor, struct span *prefix, struct span *local, struct span *full) {
    const char *start = *cursor, *p = start, *part;
    prefix->p = NULL; prefix->n = 0;
    if (!name_start((unsigned char)*p)) return 0;
    while (name_char((unsigned char)*p)) p++;
    part = start;
    if (*p == ':') {
        prefix->p = start; prefix->n = (size_t)(p-start); part = ++p;
        if (!name_start((unsigned char)*p)) return 0;
        while (name_char((unsigned char)*p)) p++;
    }
    if (*p == ':' || (size_t)(p-start) > 79) return 0;
    local->p = part; local->n = (size_t)(p-part);
    full->p = start; full->n = (size_t)(p-start); *cursor = p;
    return 1;
}
static int namespace_uri(const struct document *doc, int scope, struct span prefix, struct span *uri) {
    if (literal(prefix, "xml")) {
        uri->p = "http://www.w3.org/XML/1998/namespace"; uri->n = strlen(uri->p); return 1;
    }
    if (literal(prefix, "xmlns")) return 0;
    while (scope >= 0) {
        const struct binding *b = &doc->bindings[scope];
        if (same(prefix, b->prefix)) { *uri = b->uri; return 1; }
        scope = b->previous;
    }
    uri->p = NULL; uri->n = 0;
    return prefix.n == 0;
}
static void whitespace(const char **p) { while (isspace((unsigned char)**p)) (*p)++; }
static int parse_xml(const char *xml, struct document *doc) {
    const char *p = xml;
    int stack[XML_DEPTH], depth = 0, root_finished = 0, declaration = 0;
    memset(doc, 0, sizeof(*doc));
    if (strnlen(xml, PACKET_MAX + 1) >= PACKET_MAX) return 0;
    while (*p) {
        if (*p != '<') {
            const char *start = p;
            int text = 0;
            while (*p && *p != '<') {
                if (*p == '&') return 0;
                if (!isspace((unsigned char)*p)) text = 1;
                p++;
            }
            if (!depth && text) return 0;
            if (depth && p != start && text) doc->nodes[stack[depth-1]].text = 1;
            continue;
        }
        if (!strncmp(p, "<?xml", 5) && isspace((unsigned char)p[5]) && !doc->count && !declaration) {
            const char *end = strstr(p+5, "?>");
            if (!end || memchr(p, '&', (size_t)(end-p))) return 0;
            declaration = 1; p = end+2; continue;
        }
        if (p[1] == '!' || p[1] == '?') return 0;
        if (p[1] == '/') {
            struct span prefix, local, full;
            struct node *node;
            const char *end = p;
            p += 2;
            if (!depth || !qname(&p, &prefix, &local, &full)) return 0;
            node = &doc->nodes[stack[depth-1]];
            if (!same(node->qname, full)) return 0;
            whitespace(&p); if (*p++ != '>') return 0;
            node->content.n = (size_t)(end-node->content.p);
            if (!--depth) root_finished = 1;
            continue;
        }
        {
            struct attribute attrs[XML_ATTRIBUTES];
            struct span prefix, local, full, uri;
            struct node *node;
            unsigned used = 0, a, b, index;
            int scope = depth ? doc->nodes[stack[depth-1]].scope : -1, self_closing = 0;
            p++;
            if (root_finished || depth == XML_DEPTH || doc->count == XML_NODES
                || !qname(&p, &prefix, &local, &full)) return 0;
            while (*p && *p != '>' && *p != '/') {
                struct attribute *attr;
                struct span ignored;
                const char *start;
                char quote;
                if (!isspace((unsigned char)*p)) return 0;
                whitespace(&p); if (*p == '>' || *p == '/') break;
                if (used == XML_ATTRIBUTES) return 0;
                attr = &attrs[used++];
                if (!qname(&p, &attr->prefix, &attr->local, &ignored)) return 0;
                whitespace(&p); if (*p++ != '=') return 0;
                whitespace(&p); quote = *p++;
                if (quote != '\'' && quote != '"') return 0;
                start = p;
                while (*p && *p != quote) { if (*p == '<' || *p == '&') return 0; p++; }
                if (!*p) return 0;
                attr->value.p = start; attr->value.n = (size_t)(p++-start);
                attr->declaration = literal(attr->prefix, "xmlns")
                    || (!attr->prefix.n && literal(attr->local, "xmlns"));
            }
            if (*p == '/') { self_closing = 1; p++; }
            if (*p++ != '>') return 0;
            for (a = 0; a < used; a++) if (attrs[a].declaration) {
                struct span bound = attrs[a].prefix.n ? attrs[a].local : attrs[a].prefix;
                struct span value = attrs[a].value;
                if (literal(bound, "xmlns") || (bound.n && !value.n)
                    || literal(value, "http://www.w3.org/2000/xmlns/")
                    || (literal(bound, "xml") != literal(value, "http://www.w3.org/XML/1998/namespace"))) return 0;
                for (b = 0; b < a; b++) if (attrs[b].declaration) {
                    struct span previous = attrs[b].prefix.n ? attrs[b].local : attrs[b].prefix;
                    if (same(bound, previous)) return 0;
                }
                if (doc->binding_count == XML_BINDINGS || value.n > 255) return 0;
                doc->bindings[doc->binding_count].prefix = bound;
                doc->bindings[doc->binding_count].uri = value;
                doc->bindings[doc->binding_count].previous = scope;
                scope = (int)doc->binding_count++;
            }
            if (!namespace_uri(doc, scope, prefix, &uri)) return 0;
            index = doc->count++; node = &doc->nodes[index];
            node->qname = full; node->local = local; node->uri = uri; node->scope = scope;
            node->first = node->last = node->next = -1; node->content.p = p;
            for (a = 0; a < used; a++) if (!attrs[a].declaration) {
                struct span attr_uri = {NULL, 0};
                if (attrs[a].prefix.n && !namespace_uri(doc, scope, attrs[a].prefix, &attr_uri)) return 0;
                for (b = 0; b < a; b++) if (!attrs[b].declaration) {
                    struct span previous_uri = {NULL, 0};
                    if (attrs[b].prefix.n && !namespace_uri(doc, scope, attrs[b].prefix, &previous_uri)) return 0;
                    if (same(attrs[a].local, attrs[b].local) && same(attr_uri, previous_uri)) return 0;
                }
                if (!attr_uri.n && literal(attrs[a].local, "MatchBy")) node->match_by = attrs[a].value;
            }
            if (depth) {
                struct node *parent = &doc->nodes[stack[depth-1]];
                if (parent->last >= 0) doc->nodes[parent->last].next = (int)index;
                else parent->first = (int)index;
                parent->last = (int)index;
            }
            if (!self_closing) stack[depth++] = (int)index;
            else if (!depth) root_finished = 1;
        }
    }
    return doc->count > 0 && root_finished && !depth;
}
static int is_node(const struct document *doc, int index, const char *uri, const char *local) {
    return index >= 0 && literal(doc->nodes[index].uri, uri) && literal(doc->nodes[index].local, local);
}
static int child(const struct document *doc, int parent, const char *uri, const char *local) {
    int index, found = -1;
    for (index = doc->nodes[parent].first; index >= 0; index = doc->nodes[index].next)
        if (is_node(doc, index, uri, local)) { if (found >= 0) return -2; found = index; }
    return found;
}
static int text(const struct document *doc, int index, char *out, size_t capacity) {
    struct span value;
    if (index < 0 || doc->nodes[index].first >= 0) return 0;
    value = doc->nodes[index].content;
    while (value.n && isspace((unsigned char)*value.p)) { value.p++; value.n--; }
    while (value.n && isspace((unsigned char)value.p[value.n-1])) value.n--;
    if (value.n >= capacity) return 0;
    if (value.n) memcpy(out, value.p, value.n);
    out[value.n] = 0; return 1;
}
static int types_match(const struct document *doc, int index) {
    char types[512], *save = NULL, *token;
    if (index == -1) return 1;
    if (!text(doc, index, types, sizeof(types))) return 0;
    for (token = strtok_r(types, " \r\n\t", &save); token; token = strtok_r(NULL, " \r\n\t", &save)) {
        struct span prefix, local, full, uri;
        const char *p = token;
        if (!qname(&p, &prefix, &local, &full) || *p
            || !namespace_uri(doc, doc->nodes[index].scope, prefix, &uri)) return 0;
        if (!(literal(uri, NETWORK) && literal(local, "NetworkVideoTransmitter"))
            && !(literal(uri, DEVICE) && literal(local, "Device"))) return 0;
    }
    return 1;
}
static int scopes_match(const struct document *doc, int index) {
    char scopes[1024], *save = NULL, *token;
    static const char *known[] = {
        "onvif://www.onvif.org/type/video_encoder", "onvif://www.onvif.org/name/LSCamoflash",
        "onvif://www.onvif.org/hardware/SZB22705", "onvif://www.onvif.org/location/anywhere"
    };
    if (index == -1) return 1;
    if (index < 0 || !text(doc, index, scopes, sizeof(scopes))) return 0;
    if (doc->nodes[index].match_by.p
        && !literal(doc->nodes[index].match_by, DISCOVERY "/rfc2396")
        && !literal(doc->nodes[index].match_by, DISCOVERY "/rfc3986")) return 0;
    for (token = strtok_r(scopes, " \r\n\t", &save); token; token = strtok_r(NULL, " \r\n\t", &save)) {
        size_t i; int found = 0;
        for (i = 0; i < sizeof(known) / sizeof(*known); ++i) {
            size_t length = strlen(token);
            if (!strncmp(known[i], token, length) && (known[i][length] == 0 || known[i][length] == '/')) found = 1;
        }
        if (!found) return 0;
    }
    return 1;
}

/* Input never appears in the response except a strictly validated UUID ID. */
static int response(const char *xml, const char *uuid, const char *xaddr,
                    unsigned sequence, char *out, size_t capacity) {
    char action[160], id[80], target[80];
    struct document doc;
    const char *kind, *match;
    int n, header, body, operation, index;
    if (!parse_xml(xml, &doc) || !is_node(&doc, 0, SOAP, "Envelope") || doc.nodes[0].text) return 0;
    header = child(&doc, 0, SOAP, "Header"); body = child(&doc, 0, SOAP, "Body");
    if (header < 0 || body < 0 || doc.nodes[0].first != header || doc.nodes[header].next != body
        || doc.nodes[body].next >= 0 || doc.nodes[header].text || doc.nodes[body].text
        || !text(&doc, child(&doc, header, ADDRESSING, "Action"), action, sizeof(action))
        || !text(&doc, child(&doc, header, ADDRESSING, "MessageID"), id, sizeof(id)) ||
        strncmp(id, "urn:uuid:", 9) || !uuid_valid(id + 9)) return 0;
    operation = doc.nodes[body].first;
    if (operation < 0 || doc.nodes[operation].next >= 0 || doc.nodes[operation].text) return 0;
    if (!strcmp(action, DISCOVERY "/Probe")) {
        if (!is_node(&doc, operation, DISCOVERY, "Probe")) return 0;
        for (index = doc.nodes[operation].first; index >= 0; index = doc.nodes[index].next)
            if (!is_node(&doc, index, DISCOVERY, "Types") && !is_node(&doc, index, DISCOVERY, "Scopes")) return 0;
        if (!types_match(&doc, child(&doc, operation, DISCOVERY, "Types"))
            || !scopes_match(&doc, child(&doc, operation, DISCOVERY, "Scopes"))) return 0;
        kind = "ProbeMatches"; match = "ProbeMatch";
    } else if (!strcmp(action, DISCOVERY "/Resolve")) {
        int endpoint = child(&doc, operation, ADDRESSING, "EndpointReference");
        if (!is_node(&doc, operation, DISCOVERY, "Resolve") || endpoint < 0
            || doc.nodes[operation].first != endpoint || doc.nodes[endpoint].next >= 0 || doc.nodes[endpoint].text
            || !text(&doc, child(&doc, endpoint, ADDRESSING, "Address"), target, sizeof(target)) ||
            strncmp(target, "urn:uuid:", 9) || strcasecmp(target + 9, uuid)) return 0;
        kind = "ResolveMatches"; match = "ResolveMatch";
    } else return 0;
    n = snprintf(out, capacity,
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" "
        "xmlns:a=\"" ADDRESSING "\" xmlns:d=\"" DISCOVERY "\" "
        "xmlns:dn=\"http://www.onvif.org/ver10/network/wsdl\" "
        "xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\">"
        "<s:Header><a:Action>" DISCOVERY "/%s</a:Action>"
        "<a:MessageID>urn:uuid:%.24s%012llx</a:MessageID>"
        "<a:RelatesTo>%s</a:RelatesTo><a:To>" ADDRESSING "/role/anonymous</a:To>"
        "<d:AppSequence InstanceId=\"%u\" MessageNumber=\"%u\"/></s:Header>"
        "<s:Body><d:%s><d:%s><a:EndpointReference><a:Address>urn:uuid:%s</a:Address>"
        "</a:EndpointReference><d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types>"
        "<d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/name/LSCamoflash "
        "onvif://www.onvif.org/hardware/SZB22705 onvif://www.onvif.org/location/anywhere</d:Scopes>"
        "<d:XAddrs>%s</d:XAddrs><d:MetadataVersion>1</d:MetadataVersion>"
        "</d:%s></d:%s></s:Body></s:Envelope>",
        kind, uuid, (unsigned long long)((message_nonce + sequence) & UINT64_C(0xffffffffffff)), id, instance_id, sequence, kind, match, uuid, xaddr, match, kind);
    return n > 0 && (size_t)n < capacity ? n : 0;
}

int main(int argc, char **argv) {
    const char *interface = NULL, *xaddr = NULL, *uuid = NULL;
    struct ifreq request; struct sockaddr_in local, peer; struct ip_mreq membership;
    char input[PACKET_MAX + 1], output[4096], expected[128];
    int fd, yes = 1, port = 3702, i, count = 0;
    unsigned sequence = 0; time_t second = 0;
    for (i = 1; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--interface")) interface = argv[i + 1];
        else if (!strcmp(argv[i], "--xaddr")) xaddr = argv[i + 1];
        else if (!strcmp(argv[i], "--uuid")) uuid = argv[i + 1];
        else if (!strcmp(argv[i], "--port")) {
            char *end; long value = strtol(argv[i + 1], &end, 10);
            if (*end || value < 1024 || value > 65535) return 2;
            port = (int)value;
        } else return 2;
    }
    if (i != argc || !interface || strlen(interface) >= IFNAMSIZ || !xaddr || !uuid || !uuid_valid(uuid)) return 2;
    fd = open("/dev/urandom", O_RDONLY); if (fd < 0) return 1;
    if (read(fd, &message_nonce, sizeof(message_nonce)) != sizeof(message_nonce)) { close(fd); return 1; }
    close(fd); instance_id = (unsigned)time(NULL);
    fd = socket(AF_INET, SOCK_DGRAM, 0); if (fd < 0) return 1;
    memset(&request, 0, sizeof(request)); strncpy(request.ifr_name, interface, IFNAMSIZ - 1);
    if (ioctl(fd, SIOCGIFADDR, &request)) { close(fd); return 1; }
    membership.imr_interface = ((struct sockaddr_in *)&request.ifr_addr)->sin_addr;
    snprintf(expected, sizeof(expected), "http://%s:5000/", inet_ntoa(membership.imr_interface));
    if (strcmp(expected, xaddr)) { close(fd); return 2; }
    memset(&local, 0, sizeof(local)); local.sin_family = AF_INET;
    local.sin_port = htons((uint16_t)port); local.sin_addr.s_addr = INADDR_ANY;
    inet_pton(AF_INET, "239.255.255.250", &membership.imr_multiaddr);
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes)) ||
        setsockopt(fd, SOL_SOCKET, SO_BINDTODEVICE, interface, strlen(interface) + 1) ||
        bind(fd, (struct sockaddr *)&local, sizeof(local)) ||
        setsockopt(fd, IPPROTO_IP, IP_ADD_MEMBERSHIP, &membership, sizeof(membership))) { close(fd); return 1; }
    signal(SIGTERM, stop_signal); signal(SIGINT, stop_signal);
    while (!stopping) {
        struct pollfd pending = {fd, POLLIN, 0}; socklen_t peer_length = sizeof(peer);
        ssize_t bytes; int length; time_t now;
        if (poll(&pending, 1, 1000) <= 0 || !(pending.revents & POLLIN)) continue;
        bytes = recvfrom(fd, input, PACKET_MAX, MSG_TRUNC, (struct sockaddr *)&peer, &peer_length);
        if (bytes <= 0 || bytes >= PACKET_MAX || memchr(input, 0, (size_t)bytes)) continue;
        if (peer.sin_addr.s_addr == INADDR_ANY || IN_MULTICAST(ntohl(peer.sin_addr.s_addr))) continue;
        now = time(NULL); if (now != second) { second = now; count = 0; }
        if (++count > 5) continue;
        input[bytes] = 0;
        length = response(input, uuid, xaddr, ++sequence, output, sizeof(output));
        if (length) sendto(fd, output, (size_t)length, 0, (struct sockaddr *)&peer, peer_length);
    }
    close(fd); return 0;
}
